"""The marketplace listing: filters, sorting, discount against M.R.P., ratings from verified buyers, store pages."""
from decimal import Decimal as D

from django.test import Client, TestCase, override_settings

from shop import services as shop
from shop.models import Product, Review, SellerSettings
from shop.tests.test_fulfilment import live
from shop.tests.test_shop import ADDRESS, household
from web.tests.test_market_web import NOTIFY_MEM, make_farmer


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, SHOP_SELLER_PCT="3", SHOP_BUYER_PCT="5", SHOP_FREE_DELIVERY_ABOVE=999)
class CatalogueTests(TestCase):
    def setUp(self):
        self.maker = make_farmer()
        SellerSettings.objects.create(user=self.maker, legal_name="Ramesh Kushwaha", address="x", village="Naigarhi", district="Rewa", state="Madhya Pradesh",
                                      pincode="486001")
        self.stole = live(self.maker, price=D("1000"), mrp=D("1400"), highlights="Hand block printed\nNatural dyes", details="Material: Cotton")
        self.honey = live(self.maker, category="food", title="Forest honey", price=D("300"), fssai_no="12345678901234", state="Chhattisgarh")

    def page(self, url):
        return Client().get(url + ("&" if "?" in url else "?") + "lang=en").content.decode()

    def test_card_shows_price_mrp_discount_and_place(self):
        html = self.page("/shop/")
        self.assertIn("1,050", html)  # 1000 + 5%
        self.assertIn("<s>₹1,470</s>", html)  # M.R.P. with the same fee
        self.assertIn("29% off", html)
        self.assertIn("Naigarhi, Rewa, Madhya Pradesh", html)
        self.assertIn("2 results", html)

    def test_filters_and_sort(self):
        self.assertNotIn("Forest honey", self.page("/shop/?price=500-1000"))
        self.assertIn("Bagh print stole", self.page("/shop/?price=1000-2500"))
        self.assertNotIn("Bagh print stole", self.page("/shop/?state=Chhattisgarh"))
        self.assertIn("Forest honey", self.page("/shop/?q=honey"))
        html = self.page("/shop/?sort=price_low")
        self.assertLess(html.index("Forest honey"), html.index("Bagh print stole"))
        self.assertNotIn("Forest honey", self.page("/shop/?rating=4"))

    def test_only_a_buyer_who_received_it_can_rate_and_the_rating_shows(self):
        buyer = household()
        o = shop.place_order(buyer, {str(self.stole.pk): 1}, ADDRESS)
        line = o.lines.get()
        bc = Client()
        bc.force_login(buyer)
        bc.post(f"/shop/review/{line.pk}/", {"stars": "5"})
        self.assertFalse(Review.objects.exists())  # not delivered yet
        o.status = "delivered"
        o.save()
        self.assertContains(bc.get(f"/shop/orders/{o.number}/?lang=en"), "Rate this product")
        bc.post(f"/shop/review/{line.pk}/", {"stars": "4", "title": "Lovely", "text": "Call me on 9876543210"})
        r = Review.objects.get()
        self.assertEqual(r.stars, 4)
        self.assertNotIn("9876543210", r.text)
        html = self.page(f"/shop/p/{self.stole.pk}/")
        for bit in ("Lovely", "Verified purchase", "1 ratings", "Hand block printed", "Material", "Visit the Ramesh Kushwaha store"):
            self.assertIn(bit, html)
        self.assertIn("Bagh print stole", self.page("/shop/?rating=4"))
        other = Client()
        other.force_login(household("9844444449"))
        self.assertEqual(other.post(f"/shop/review/{line.pk}/", {"stars": "1"}).status_code, 404)

    def test_store_page_lists_only_that_makers_products(self):
        other = make_farmer("9000000777")
        live(other, title="Bamboo lamp", category="decor")
        html = self.page(f"/shop/m/{self.maker.pk}/")
        self.assertIn("Ramesh Kushwaha", html)
        self.assertIn("Bagh print stole", html)
        self.assertNotIn("Bamboo lamp", html)

    def test_mrp_below_the_price_is_refused(self):
        mc = Client()
        mc.force_login(self.maker)
        mc.post("/shop/manage/new/", {"category": "handloom", "title": "Durrie", "pack": "1", "description": "Cotton rug", "asked_price": "900", "mrp": "500",
                                      "max_per_order": "5", "fulfilment": "seller", "village": "v", "district": "Rewa", "state": "Madhya Pradesh",
                                      "weight_g": "500", "gst_rate": "0"})
        self.assertFalse(Product.objects.filter(title="Durrie").exists())
