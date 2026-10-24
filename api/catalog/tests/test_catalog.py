from io import StringIO
from decimal import Decimal

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

import catalog
from catalog import odop, services
from catalog.models import DistrictProduct
from farmerbook.models import CropCycle, Harvest, Plot, Processing, Sale
from farmerbook.serializers import processed_stock, stock_kg
from market import services as market_services
from market import stock
from market.models import Listing
from rates.crops import CROPS, canonical_crop
from rates.models import MarketRate
from web.tests.test_market_web import TODAY, make_buyer, make_farmer, stocked_cycle


class DataTests(TestCase):
    def test_every_conversion_points_at_real_products_and_needs(self):
        for frm, to, y, cost, price, needs, how in catalog.CONVERSIONS:
            self.assertIn(frm, catalog.PRODUCTS, frm)
            self.assertEqual(catalog.kind(to), catalog.SEMI, to)
            self.assertIn(catalog.kind(frm), (catalog.RAW, catalog.FRESH), frm)
            self.assertTrue(0 < y[0] <= y[1] <= 150, (frm, to))
            self.assertTrue(0 < price[0] <= price[1], (frm, to))
            self.assertTrue(all(n in catalog.NEEDS for n in needs))
            self.assertEqual(len(how), 3)

    def test_every_processed_product_can_be_made_from_something(self):
        made = {c[1] for c in catalog.CONVERSIONS}
        self.assertEqual({k for k in catalog.PRODUCTS if catalog.kind(k) == catalog.SEMI}, made)

    def test_names_exist_in_three_languages(self):
        for key, (en, hi, mr, emoji, kind) in catalog.PRODUCTS.items():
            self.assertTrue(all([en, hi, mr, emoji]), key)

    def test_mandi_names_reach_the_new_crops_and_dry_forms_stay_out(self):
        self.assertEqual(canonical_crop("Ginger(Green)"), "ginger")
        self.assertEqual(canonical_crop("Ginger(Dry)"), "")
        self.assertEqual(canonical_crop("Mousambi(Sweet Orange)"), "orange")
        self.assertIn("mushroom", CROPS)
        self.assertNotIn("dry_mushroom", CROPS)


class ValueTests(TestCase):
    def test_dried_mushroom_is_worth_more_than_fresh_and_the_gain_uses_todays_rate(self):
        MarketRate.objects.create(source="agmarknet", date=TODAY, state="Madhya Pradesh", district="Rewa", market="Rewa", commodity="Mushroom", variety="x", crop="mushroom",
                                  min_price=9000, max_price=11000, modal_price=10000)
        opts = {o["to"]: o for o in services.value_options("mushroom", "Madhya Pradesh", "Rewa")}
        dry = opts["dry_mushroom"]
        self.assertEqual(dry["raw_value"], Decimal("10000"))  # 100 kg at 100 a kg
        self.assertEqual(dry["kg_out"], Decimal("10.0"))      # middle of 8-12 kg
        self.assertEqual(dry["revenue"], Decimal("10500"))    # 10 kg at the middle of 700-1400
        self.assertEqual(dry["gain"], Decimal("10500") - 1200 - 10000)
        self.assertEqual(dry["price"]["source"], "estimate")

    def test_without_a_mandi_price_the_gain_is_not_made_up(self):
        opts = services.value_options("mushroom", "Madhya Pradesh", "Rewa")
        self.assertTrue(opts and all(o["gain"] is None for o in opts))

    def test_live_listings_replace_the_estimate(self):
        farmer = make_farmer()
        for q in (1, 2):
            cycle = stocked_cycle(farmer, 10)
            Processing.objects.create(owner=farmer, crop_cycle=cycle, date=TODAY, product="atta", input_kg=1000, quantity=800, unit="kg", quantity_kg=800)
            market_services.save_listing(farmer, {"crop": "atta", "quantity": Decimal("100"), "unit": "kg", "price": Decimal("40"), "state": "Madhya Pradesh", "district": "Rewa", "source_cycle": cycle})
        ref = services.reference_price("atta", "Madhya Pradesh")
        self.assertEqual((ref["source"], ref["n"], ref["typical"]), ("listings", 2, Decimal("40")))


class ProcessingBookTests(TestCase):
    def setUp(self):
        self.farmer = make_farmer()
        self.cycle = stocked_cycle(self.farmer, 10, crop="wheat")  # 1000 kg
        self.c = Client()
        self.c.force_login(self.farmer)

    def process(self, **over):
        data = {"product": "atta", "date": TODAY.isoformat(), "input_quantity": "4", "input_unit": "quintal", "quantity": "300", "unit": "kg", "cost": "900", "packaging": "bulk"}
        data.update(over)
        return self.c.post(f"/farmer/book/{self.cycle.client_id}/add/process/", data)

    def test_processing_moves_stock_and_adds_the_cost(self):
        r = self.process()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(stock_kg(self.cycle), Decimal("600"))
        self.assertEqual(processed_stock(self.cycle), {"atta": Decimal("300.000")})
        from farmerbook.views import cycle_summary
        s = cycle_summary(self.cycle)
        self.assertEqual((s["expenses"], s["stock_kg"], s["processed_stock"]), ("900.00", "600.000", {"atta": "300.000"}))

    def test_cannot_process_more_than_is_in_stock_or_get_impossible_output(self):
        self.assertEqual(self.process(input_quantity="11").status_code, 200)
        self.assertEqual(self.process(quantity="2000").status_code, 200)  # 2,000 kg from 400 kg
        self.assertEqual(Processing.objects.count(), 0)

    def test_only_products_made_from_this_crop_are_offered(self):
        self.assertEqual(self.process(product="dry_mushroom").status_code, 200)
        self.assertEqual(Processing.objects.count(), 0)

    def test_selling_processed_stock_is_limited_to_what_was_made(self):
        self.process()
        url = f"/farmer/book/{self.cycle.client_id}/add/sale/"
        base = {"product": "atta", "date": TODAY.isoformat(), "unit": "kg", "rate": "35", "channel": "other"}
        self.assertEqual(self.c.post(url, {**base, "quantity": "400"}).status_code, 200)
        self.assertEqual(self.c.post(url, {**base, "quantity": "250"}).status_code, 302)
        self.assertEqual(processed_stock(self.cycle), {"atta": Decimal("50.000")})
        self.assertEqual(stock_kg(self.cycle), Decimal("600"))  # the raw stock was not touched
        from farmerbook.views import cycle_summary
        self.assertEqual(cycle_summary(self.cycle)["revenue"], "8750.00")

    def test_an_undone_batch_cannot_be_removed_once_some_is_sold(self):
        self.process()
        self.c.post(f"/farmer/book/{self.cycle.client_id}/add/sale/", {"product": "atta", "date": TODAY.isoformat(), "quantity": "100", "unit": "kg", "rate": "35", "channel": "other"})
        rec = Processing.objects.get()
        self.c.post(f"/farmer/book/{self.cycle.client_id}/delete/process/{rec.client_id}/")
        rec.refresh_from_db()
        self.assertEqual(Processing.objects.filter(deleted_at__isnull=True).count(), 1)  # 100 kg was sold, so the batch stays

    def test_the_book_pages_render_in_all_languages(self):
        self.process()
        for lang in ("hi", "mr", "en"):
            for path in (f"/farmer/book/{self.cycle.client_id}/", f"/farmer/book/{self.cycle.client_id}/add/process/", f"/farmer/book/{self.cycle.client_id}/add/sale/", "/farmer/", "/value/", "/value/wheat/", "/value/wheat/?qty=12"):
                self.assertEqual(self.c.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").status_code, 200, path)


class ProcessedListingTests(TestCase):
    def setUp(self):
        self.farmer = make_farmer()
        self.buyer = make_buyer()
        self.cycle = stocked_cycle(self.farmer, 10, crop="wheat")
        Processing.objects.create(owner=self.farmer, crop_cycle=self.cycle, date=TODAY, product="atta", input_kg=500, quantity=380, unit="kg", quantity_kg=380, shelf_life_days=90)
        self.c = Client()
        self.c.force_login(self.farmer)

    FORM = {"quantity": "380", "unit": "kg", "price": "38", "state": "Madhya Pradesh", "district": "Rewa", "available_from": TODAY.isoformat(), "packaging": "bulk", "shelf_life_days": "90"}

    def test_the_picker_lists_the_crop_and_what_was_made_from_it(self):
        page = self.c.get("/farmer/sell/pick/?lang=en").content.decode()
        self.assertIn("Wheat flour (atta)", page)
        self.assertIn("made from", page)
        self.assertIn("product=atta", page)

    def test_listing_processed_stock_in_bulk_then_packed_needs_an_fssai_number(self):
        r = self.c.post("/farmer/sell/new/", {**self.FORM, "stock": self.cycle.pk, "product": "atta"})
        li = Listing.objects.get()
        self.assertEqual((li.crop, li.form, li.packaging, li.source_cycle, li.price_per_quintal), ("atta", "semi", "bulk", self.cycle, Decimal("3800.00")))
        li.delete()
        packed = {**self.FORM, "stock": self.cycle.pk, "product": "atta", "packaging": "packed", "pack_size_g": "1000", "brand": "Kushwaha Farms"}
        self.assertEqual(self.c.post("/farmer/sell/new/", {**packed, "fssai_no": "123"}).status_code, 200)
        self.assertEqual(Listing.objects.count(), 0)
        self.assertEqual(self.c.post("/farmer/sell/new/", {**packed, "fssai_no": "1234 5678 901234"}).status_code, 302)
        li = Listing.objects.get()
        self.assertEqual((li.packaging, li.pack_size_g, li.fssai_no, li.brand), ("packed", 1000, "12345678901234", "Kushwaha Farms"))

    def test_processed_stock_limit_is_its_own(self):
        r = self.c.post("/farmer/sell/new/", {**self.FORM, "stock": self.cycle.pk, "product": "atta", "quantity": "381"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Only 380 kg")
        # wheat itself is still free to list: 1000 - 500 went into processing
        self.assertEqual(stock.free_kg(self.cycle, "wheat"), Decimal("500"))
        self.assertEqual(stock.free_kg(self.cycle, "atta"), Decimal("380"))

    def test_browse_filters_by_kind_and_packaging_and_shows_the_reference(self):
        self.c.post("/farmer/sell/new/", {**self.FORM, "stock": self.cycle.pk, "product": "atta"})
        market_services.save_listing(self.farmer, {"crop": "wheat", "quantity": Decimal("5"), "unit": "quintal", "price": Decimal("2500"), "state": "Madhya Pradesh", "district": "Rewa", "source_cycle": self.cycle})
        anon = self.c  # everything is behind sign-in now
        self.assertContains(anon.get("/market/?kind=semi&lang=en"), "Wheat flour (atta)")
        self.assertNotContains(anon.get("/market/?kind=semi&lang=en"), ">Wheat<")
        self.assertEqual(len(anon.get("/market/?kind=raw").context["rows"]), 1)
        self.assertEqual(len(anon.get("/market/?packed=1").context["rows"]), 0)
        page = anon.get(f"/market/{Listing.objects.get(crop='atta').pk}/?lang=en").content.decode()
        self.assertIn("Starter estimate", page)
        self.assertIn("per kg", page)


class DistrictProductTests(TestCase):
    def test_loader_reads_all_713_official_rows_and_maps_crops(self):
        call_command("load_odop", stdout=StringIO())
        self.assertEqual(DistrictProduct.objects.count(), 713)
        rewa = DistrictProduct.objects.get(state="Madhya Pradesh", district="Rewa")
        self.assertEqual((rewa.product.strip(), rewa.crops), ("Turmeric", ["turmeric"]))
        self.assertEqual(DistrictProduct.objects.get(district="Balaghat").crops, ["kodo", "kutki"])
        call_command("load_odop", stdout=StringIO())
        self.assertEqual(DistrictProduct.objects.count(), 713)

    def test_matcher(self):
        self.assertEqual(odop.crops_for("Tomato based Products"), ["tomato"])
        self.assertEqual(odop.crops_for("Orange / Citrus based Products"), ["orange"])
        self.assertEqual(odop.crops_for("Betel vine based Products"), [])

    def test_a_farmers_district_is_featured_with_the_rate_and_offers(self):
        call_command("load_odop", stdout=StringIO())
        MarketRate.objects.create(source="agmarknet", date=TODAY, state="Madhya Pradesh", district="Rewa", market="Rewa", commodity="Turmeric", variety="x", crop="turmeric",
                                  min_price=9000, max_price=11000, modal_price=10000)
        f = services.featured_for("Madhya Pradesh", "Rewa")
        self.assertEqual((f["crop"], f["rate"]["typical"]), ("turmeric", Decimal("10000")))
        self.assertTrue(f["options"])
        farmer = make_farmer()
        c = Client()
        c.force_login(farmer)
        with override_settings(RATES_SHOW_DEMO=False):
            page = c.get("/market/?lang=en").content.decode()
        self.assertIn("Known in Rewa", page)
        self.assertIn("One District One Product", page)

    def test_buyers_see_places_known_for_a_product(self):
        call_command("load_odop", stdout=StringIO())
        b = Client()
        b.force_login(make_buyer())
        self.assertContains(b.get("/market/?lang=en"), "Places known for a product")
