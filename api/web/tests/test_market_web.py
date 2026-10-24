from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User, UserStatus
from farmerbook.models import CropCycle, Harvest, Plot
from market import services
from market.models import Enquiry, EnquiryMessage, Listing
from notify.backends import MemoryBackend
from notify.models import Message
from profiles.models import Organisation, OrgMembership
from rates.models import MarketRate

NOTIFY_MEM = {"sms": "notify.backends.MemoryBackend", "whatsapp": "notify.backends.MemoryBackend"}
TODAY = timezone.localdate()
SELLER, BUYER, BUYER2, AGENT = "9876543210", "9811111111", "9822222222", "9833333333"


def make_farmer(phone=SELLER, complete=True):
    u = User.objects.create_user(phone, role=Role.FARMER, status=UserStatus.ACTIVE, consent_version="2026-10-v1", language="en")
    if complete:
        fp = u.farmer_profile
        fp.name, fp.village, fp.district, fp.state, fp.land_acres, fp.crops = "Ramesh Kushwaha", "Naigarhi", "Rewa", "Madhya Pradesh", 3, ["wheat"]
        fp.save()
    return u


def make_buyer(phone=BUYER, complete=True, name="Rao Caterers"):
    u = User.objects.create_user(phone, role=Role.BUYER, status=UserStatus.ACTIVE, consent_version="2026-10-v1", language="en")
    if complete:
        bp = u.buyer_profile
        bp.contact_name, bp.business_name, bp.business_type, bp.city = "Anita Rao", name, "caterer", "Pune"
        bp.save()
    return u


def stocked_cycle(farmer, quintals=24, crop="wheat"):
    plot = Plot.objects.create(owner=farmer, name="Home", area_acres=2)
    cycle = CropCycle.objects.create(owner=farmer, plot=plot, crop=crop)
    Harvest.objects.create(owner=farmer, crop_cycle=cycle, date=TODAY, quantity=quintals, unit="quintal", quantity_kg=quintals * 100)
    return cycle


def listing_data(**over):
    d = {"crop": "wheat", "quantity": Decimal("10"), "unit": "quintal", "price": Decimal("2500"), "grade": "A", "state": "Madhya Pradesh", "district": "Rewa", "village": "Naigarhi"}
    d.update(over)
    return d


def rate(modal=2400, crop="wheat", district="Rewa", state="Madhya Pradesh"):
    return MarketRate.objects.create(source="agmarknet", date=TODAY, state=state, district=district, market=district, commodity=crop.title(), variety="Other", crop=crop,
                                     min_price=modal - 100, max_price=modal + 100, modal_price=modal)


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, RATES_SHOW_DEMO=False)
class MarketCase(TestCase):
    def setUp(self):
        cache.clear()
        MemoryBackend.outbox.clear()
        self.seller = make_farmer()
        self.buyer = make_buyer()
        self.sc, self.bc = Client(), Client()
        self.sc.force_login(self.seller)
        self.bc.force_login(self.buyer)

    def listing(self, **over):
        if "source_cycle" not in over:  # every listing comes out of the Farmer Book
            over["source_cycle"] = stocked_cycle(self.seller, quintals=1000, crop=over.get("crop", "wheat"))
        return services.save_listing(self.seller, listing_data(**over))


class ListingRuleTests(MarketCase):
    def test_price_per_quintal_is_worked_out_whatever_the_unit(self):
        bags = self.listing(quantity=Decimal("40"), unit="bag", bag_weight_kg=Decimal("50"), price=Decimal("1200"))
        self.assertEqual((bags.quantity_kg, bags.price_per_quintal), (Decimal("2000.000"), Decimal("2400.00")))
        kilos = self.listing(quantity=Decimal("500"), unit="kg", price=Decimal("24"))
        self.assertEqual(kilos.price_per_quintal, Decimal("2400.00"))

    def test_a_bag_needs_a_weight(self):
        from accounts.errors import ApiError
        with self.assertRaises(ApiError):
            self.listing(unit="bag")

    def test_cannot_list_more_than_the_stock_in_the_book(self):
        from accounts.errors import ApiError
        cycle = stocked_cycle(self.seller, quintals=24)
        self.listing(quantity=Decimal("15"), source_cycle=cycle)
        with self.assertRaises(ApiError) as cm:
            self.listing(quantity=Decimal("10"), source_cycle=cycle)  # only 9 left unlisted
        self.assertEqual(cm.exception.code, "not_enough_stock")
        self.listing(quantity=Decimal("9"), source_cycle=cycle)

    def test_mandi_reference_compares_with_todays_price(self):
        rate(modal=2400)
        li = self.listing(price=Decimal("2520"))
        ref = services.mandi_reference(li)
        self.assertEqual((ref["typical"], ref["diff_pct"]), (Decimal("2400"), Decimal("5.0")))
        self.assertIsNone(services.mandi_reference(self.listing(crop="tomato")))

    def test_listings_expire_and_can_be_hidden(self):
        li = self.listing()
        self.assertEqual(Listing.live().count(), 1)
        Listing.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(Listing.live().count(), 0)
        Listing.objects.update(expires_at=timezone.now() + timedelta(days=1), status="hidden")
        self.assertEqual(Listing.live().count(), 0)
        li.refresh_from_db()
        self.assertFalse(li.is_live)


class MaskingTests(TestCase):
    def test_phone_numbers_emails_and_links_are_hidden(self):
        for text in ("call me on 98765 43210", "ring +91-98765-43210 now", "९८७६५४३२१०", "mail ramesh@example.com", "see www.example.com/x", "https://wa.me/919876543210"):
            masked, changed = services.mask_contacts(text)
            self.assertTrue(changed, text)
            self.assertIn("•••", masked)
            self.assertNotRegex(masked, r"[0-9०-९]{6}")
        self.assertEqual(services.mask_contacts("10 quintal at 2400 rupees by Friday"), ("10 quintal at 2400 rupees by Friday", False))

    def test_the_space_after_a_number_survives(self):
        self.assertEqual(services.mask_contacts("call 98765 43210 or text")[0], "call ••• or text")


class BrowseTests(MarketCase):
    def test_public_can_browse_but_not_see_who_the_seller_is(self):
        self.listing(description="Sharbati, clean.")
        page = Client().get("/market/?lang=en").content.decode()
        self.assertIn("Wheat", page)
        self.assertIn("Ramesh", page)  # first name and village only
        self.assertNotIn(SELLER, page)
        self.assertNotIn("Kushwaha", page)

    def test_filters_and_sorting(self):
        self.listing(price=Decimal("2600"))
        self.listing(crop="gram", price=Decimal("5600"), district="Satna")
        self.assertNotContains(Client().get("/market/?crop=gram&lang=en"), "Wheat</h3>")
        self.assertContains(Client().get("/market/?district=satn&lang=en"), "Satna")
        rows = Client().get("/market/?sort=cheap&lang=en").context["rows"]
        self.assertEqual([r.crop for r in rows], ["wheat", "gram"])

    def test_hidden_expired_and_paused_listings_are_not_listed(self):
        a, b, c = self.listing(), self.listing(), self.listing()
        Listing.objects.filter(pk=a.pk).update(status="hidden")
        Listing.objects.filter(pk=b.pk).update(status="paused")
        Listing.objects.filter(pk=c.pk).update(expires_at=timezone.now() - timedelta(days=1))
        self.assertEqual(len(Client().get("/market/").context["rows"]), 0)
        self.assertEqual(Client().get(f"/market/{a.pk}/").status_code, 404)  # hidden: gone for the public
        self.assertContains(Client().get(f"/market/{b.pk}/?lang=en"), "paused this listing")  # paused: visible but not buyable
        self.assertEqual(self.sc.get(f"/market/{a.pk}/").status_code, 200)  # the seller still sees their own hidden listing

    def test_detail_shows_the_mandi_comparison_and_value(self):
        rate(modal=2400)
        li = self.listing(price=Decimal("2520"))
        page = Client().get(f"/market/{li.pk}/?lang=en").content.decode()
        self.assertIn("₹25,200", page)
        self.assertIn("+5% compared with the mandi", page)

    def test_every_page_renders_in_all_languages(self):
        li = self.listing()
        e = services.start_enquiry(self.buyer, li, Decimal("5"), None, "hello")
        for lang in ("hi", "mr", "en"):
            for path in ("/market/", f"/market/{li.pk}/", "/farmer/sell/", "/farmer/sell/pick/", f"/farmer/sell/new/?stock={li.source_cycle.pk}", f"/farmer/sell/{li.pk}/", f"/farmer/sell/{li.pk}/edit/", "/farmer/enquiries/", f"/enquiry/{e.pk}/"):
                self.assertEqual(self.sc.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").status_code, 200, path)
            for path in ("/buyer/", "/buyer/profile/", "/buyer/enquiries/", f"/market/{li.pk}/", f"/enquiry/{e.pk}/"):
                self.assertEqual(self.bc.get(f"{path}?lang={lang}").status_code, 200, path)


class SellerWebTests(MarketCase):
    FORM = {"variety": "Sharbati", "grade": "A", "quantity": "10", "unit": "quintal", "price": "2500", "state": "Madhya Pradesh",
            "district": "Rewa", "village": "Naigarhi", "available_from": TODAY.isoformat(), "description": ""}

    def test_incomplete_profile_is_sent_to_finish_it_first(self):
        c = Client()
        c.force_login(make_farmer("9000000099", complete=False))
        self.assertRedirects(c.get("/farmer/sell/new/"), "/farmer/profile/", fetch_redirect_response=False)

    def test_list_from_stock_prefills_quantity_place_and_mandi_price(self):
        rate(modal=2400)
        cycle = stocked_cycle(self.seller, quintals=24)
        form = self.sc.get(f"/farmer/sell/new/?cycle={cycle.client_id}&lang=en").context["form"]
        self.assertEqual((form.initial["quantity"], form.initial["district"], form.initial["price"]), (Decimal("24.000"), "Rewa", Decimal("2400")))

    def test_prefilled_quantity_never_exceeds_the_stock(self):
        plot = Plot.objects.create(owner=self.seller, name="P", area_acres=1)
        cycle = CropCycle.objects.create(owner=self.seller, plot=plot, crop="wheat")
        Harvest.objects.create(owner=self.seller, crop_cycle=cycle, date=TODAY, quantity=Decimal("12.596"), unit="kg", quantity_kg=Decimal("12.596"))
        form = self.sc.get(f"/farmer/sell/new/?cycle={cycle.client_id}&lang=en").context["form"]
        self.assertEqual(form.initial["quantity"], Decimal("0.125"))  # 12.596 kg is 0.12596 quintal; rounding up would be 0.126
        data = {**self.FORM, "stock": cycle.pk, "quantity": str(form.initial["quantity"])}
        self.assertEqual(self.sc.post("/farmer/sell/new/", data).status_code, 302)

    def test_a_second_listing_of_the_same_crop_starts_from_what_is_left(self):
        cycle = stocked_cycle(self.seller, quintals=24)
        self.listing(quantity=Decimal("15"), source_cycle=cycle)
        form = self.sc.get(f"/farmer/sell/new/?cycle={cycle.client_id}&lang=en").context["form"]
        self.assertEqual(form.initial["quantity"], Decimal("9.000"))

    def test_without_a_stock_line_you_are_sent_to_pick_one_or_to_the_book(self):
        r = self.sc.get("/farmer/sell/new/")
        self.assertRedirects(r, "/farmer/sell/pick/", fetch_redirect_response=False)
        self.assertContains(self.sc.get("/farmer/sell/pick/?lang=en"), "Nothing to sell yet")
        self.assertRedirects(self.sc.get("/farmer/sell/new/?cycle=not-a-uuid"), "/farmer/sell/pick/", fetch_redirect_response=False)
        stocked_cycle(self.seller, quintals=8)
        page = self.sc.get("/farmer/sell/pick/?lang=en").content.decode()
        self.assertIn("8 quintal", page)

    def test_nothing_can_be_listed_without_book_stock(self):
        r = self.sc.post("/farmer/sell/new/", self.FORM)
        self.assertRedirects(r, "/farmer/sell/pick/", fetch_redirect_response=False)
        self.assertEqual(Listing.objects.count(), 0)

    def test_someone_elses_cycle_is_ignored(self):
        other_cycle = stocked_cycle(make_farmer("9000000066"))
        self.assertRedirects(self.sc.get(f"/farmer/sell/new/?cycle={other_cycle.client_id}"), "/farmer/sell/pick/", fetch_redirect_response=False)

    def test_create_edit_pause_sell_and_delete(self):
        cycle = stocked_cycle(self.seller, quintals=30)
        r = self.sc.post("/farmer/sell/new/", {**self.FORM, "stock": cycle.pk})
        li = Listing.objects.get()
        self.assertRedirects(r, f"/farmer/sell/{li.pk}/", fetch_redirect_response=False)
        self.assertEqual((li.seller, li.crop, li.source_cycle, li.price_per_quintal, li.variety), (self.seller, "wheat", cycle, Decimal("2500.00"), "Sharbati"))
        self.sc.post(f"/farmer/sell/{li.pk}/edit/", {**self.FORM, "price": "2600"})
        li.refresh_from_db()
        self.assertEqual(li.price, Decimal("2600"))
        self.sc.post(f"/farmer/sell/{li.pk}/action/", {"action": "pause"})
        li.refresh_from_db()
        self.assertEqual(li.status, "paused")
        self.sc.post(f"/farmer/sell/{li.pk}/action/", {"action": "resume"})
        self.sc.post(f"/farmer/sell/{li.pk}/action/", {"action": "sold"})
        li.refresh_from_db()
        self.assertEqual(li.status, "sold")
        self.sc.post(f"/farmer/sell/{li.pk}/action/", {"action": "delete"})
        self.assertEqual(Listing.objects.count(), 0)

    def test_editing_cannot_raise_the_quantity_above_the_stock(self):
        cycle = stocked_cycle(self.seller, quintals=12)
        li = self.listing(quantity=Decimal("10"), source_cycle=cycle)
        r = self.sc.post(f"/farmer/sell/{li.pk}/edit/", {**self.FORM, "quantity": "13"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Only 12 quintal")
        self.assertEqual(self.sc.post(f"/farmer/sell/{li.pk}/edit/", {**self.FORM, "quantity": "12"}).status_code, 302)

    def test_listing_with_enquiries_cannot_be_deleted(self):
        li = self.listing()
        services.start_enquiry(self.buyer, li, Decimal("2"), None, "")
        self.sc.post(f"/farmer/sell/{li.pk}/action/", {"action": "delete"})
        self.assertEqual(Listing.objects.count(), 1)

    def test_bad_price_is_refused(self):
        cycle = stocked_cycle(self.seller, quintals=30)
        self.assertEqual(self.sc.post("/farmer/sell/new/", {**self.FORM, "stock": cycle.pk, "price": "0"}).status_code, 200)
        self.assertEqual(Listing.objects.count(), 0)

    def test_stock_limit_applies_on_the_form_too(self):
        cycle = stocked_cycle(self.seller, quintals=5)
        r = self.sc.post("/farmer/sell/new/", {**self.FORM, "stock": cycle.pk, "quantity": "9"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Only 5 quintal of this is free")
        self.assertEqual(Listing.objects.count(), 0)

    def test_sellers_cannot_touch_each_others_listings(self):
        li = self.listing()
        other = Client()
        other.force_login(make_farmer("9000000088"))
        self.assertEqual(other.get(f"/farmer/sell/{li.pk}/").status_code, 404)
        self.assertEqual(other.post(f"/farmer/sell/{li.pk}/action/", {"action": "sold"}).status_code, 404)
        self.assertEqual(other.get(f"/farmer/sell/{li.pk}/edit/").status_code, 404)

    def test_buyers_and_anonymous_cannot_sell(self):
        self.assertRedirects(self.bc.get("/farmer/sell/new/"), "/buyer/", fetch_redirect_response=False)
        self.assertRedirects(Client().get("/farmer/sell/"), "/login/", fetch_redirect_response=False)

    def test_the_sold_listing_cannot_be_enquired_about(self):
        li = self.listing()
        self.sc.post(f"/farmer/sell/{li.pk}/action/", {"action": "sold"})
        r = self.bc.post(f"/market/{li.pk}/enquire/", {"quantity": "2"})
        self.assertEqual(Enquiry.objects.count(), 0)
        self.assertContains(r, "has been sold")


class FpoSellingTests(MarketCase):
    def setUp(self):
        super().setUp()
        self.org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", state="Madhya Pradesh", verified=True, contact_name="Mohan")
        self.agent = User.objects.create_user(AGENT, role=Role.AGENT, status=UserStatus.ACTIVE, language="en")
        OrgMembership.objects.create(user=self.agent, organisation=self.org)
        self.ac = Client()
        self.ac.force_login(self.agent)

    def member_stock(self, quintals=40, crop="kodo", status="confirmed"):
        farmer = make_farmer("9877700001")
        fp = farmer.farmer_profile
        fp.organisation, fp.org_status = self.org, status
        fp.save()
        return stocked_cycle(farmer, quintals=quintals, crop=crop)

    def test_an_fpo_can_list_only_from_its_member_farmers_books(self):
        self.assertContains(self.ac.get("/fpo/sell/pick/?lang=en"), "Nothing to sell yet")
        stray = stocked_cycle(make_farmer("9877700002"), quintals=40, crop="kodo")  # not a member
        self.assertRedirects(self.ac.get(f"/fpo/sell/new/?stock={stray.pk}"), "/fpo/sell/pick/", fetch_redirect_response=False)
        cycle = self.member_stock()
        page = self.ac.get("/fpo/sell/pick/?lang=en").content.decode()
        self.assertIn("Ramesh Kushwaha", page)
        self.assertEqual(self.ac.get(f"/fpo/sell/new/?stock={cycle.pk}").status_code, 200)

    def test_a_verified_fpo_lists_in_its_own_name(self):
        cycle = self.member_stock()
        r = self.ac.post("/fpo/sell/new/", {**SellerWebTests.FORM, "stock": cycle.pk, "quantity": "30"})
        li = Listing.objects.get()
        self.assertRedirects(r, f"/fpo/sell/{li.pk}/", fetch_redirect_response=False)
        self.assertEqual(li.organisation, self.org)
        page = Client().get(f"/market/{li.pk}/?lang=en").content.decode()
        self.assertIn("Naigarhi FPO", page)
        self.assertIn("Verified", page)

    def test_an_unverified_fpo_cannot_list(self):
        Organisation.objects.update(verified=False)
        self.assertRedirects(self.ac.get("/fpo/sell/new/"), "/fpo/", fetch_redirect_response=False)

    def test_buyer_sees_the_fpo_contact_after_accept(self):
        li = services.save_listing(self.agent, listing_data(crop="kodo", source_cycle=self.member_stock()), org=self.org)
        e = services.start_enquiry(self.buyer, li, Decimal("5"), None, "")
        services.decide(e, self.agent, True)
        page = self.bc.get(f"/enquiry/{e.pk}/?lang=en").content.decode()
        self.assertIn("Naigarhi FPO", page)
        self.assertIn(AGENT, page)


class EnquiryTests(MarketCase):
    def setUp(self):
        super().setUp()
        self.li = self.listing()

    def test_a_buyer_with_a_profile_can_ask_and_the_seller_is_told(self):
        r = self.bc.post(f"/market/{self.li.pk}/enquire/", {"quantity": "4", "offered_price": "2450", "message": "Can you deliver to Satna?"})
        e = Enquiry.objects.get()
        self.assertRedirects(r, f"/enquiry/{e.pk}/", fetch_redirect_response=False)
        self.assertEqual((e.quantity, e.offered_price, e.status), (Decimal("4"), Decimal("2450"), "new"))
        self.assertEqual(e.messages.get().text, "Can you deliver to Satna?")
        m = Message.objects.get()
        self.assertEqual((m.phone, m.template, m.related), (SELLER, "enquiry_received", f"enquiry:{e.pk}"))
        self.assertIn(f"/enquiry/{e.pk}/", m.text)

    def test_the_sellers_message_is_in_the_sellers_language_and_names_the_crop(self):
        User.objects.filter(pk=self.seller.pk).update(language="hi")
        services.start_enquiry(self.buyer, Listing.objects.get(pk=self.li.pk), Decimal("4"), None, "")
        text = Message.objects.get().text
        self.assertIn("गेहूँ", text)
        self.assertIn("क्विंटल", text)

    def test_one_conversation_per_buyer_per_listing(self):
        self.bc.post(f"/market/{self.li.pk}/enquire/", {"quantity": "4"})
        r = self.bc.post(f"/market/{self.li.pk}/enquire/", {"quantity": "9"})
        self.assertEqual(Enquiry.objects.count(), 1)
        self.assertEqual(Enquiry.objects.get().quantity, Decimal("4"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Message.objects.count(), 1)

    def test_rules(self):
        from accounts.errors import ApiError
        with self.assertRaises(ApiError) as cm:
            services.start_enquiry(self.seller, self.li, Decimal("1"), None, "")
        self.assertEqual(cm.exception.code, "buyers_only")
        with self.assertRaises(ApiError) as cm:
            services.start_enquiry(make_buyer("9844444444", complete=False), self.li, Decimal("1"), None, "")
        self.assertEqual(cm.exception.code, "profile_incomplete")
        with self.assertRaises(ApiError) as cm:
            services.start_enquiry(self.buyer, self.li, Decimal("11"), None, "")  # more than the 10 listed
        self.assertEqual(cm.exception.code, "bad_quantity")
        self.assertEqual(Enquiry.objects.count(), 0)

    def test_incomplete_buyer_is_sent_to_the_profile(self):
        c = Client()
        c.force_login(make_buyer("9855555555", complete=False))
        self.assertRedirects(c.post(f"/market/{self.li.pk}/enquire/", {"quantity": "2"}), "/buyer/profile/", fetch_redirect_response=False)

    def test_only_buyers_can_post_the_form(self):
        self.assertRedirects(self.sc.post(f"/market/{self.li.pk}/enquire/", {"quantity": "2"}), "/farmer/", fetch_redirect_response=False)
        self.assertRedirects(Client().post(f"/market/{self.li.pk}/enquire/", {"quantity": "2"}), "/login/", fetch_redirect_response=False)


class ConversationTests(MarketCase):
    def setUp(self):
        super().setUp()
        self.li = self.listing(source_cycle=stocked_cycle(self.seller))
        self.e = services.start_enquiry(self.buyer, self.li, Decimal("4"), Decimal("2450"), "")
        MemoryBackend.outbox.clear()
        Message.objects.all().delete()

    def say(self, client, text):
        return client.post(f"/enquiry/{self.e.pk}/message/", {"text": text})

    def test_phone_numbers_are_hidden_until_the_seller_accepts(self):
        self.say(self.bc, "Call me on 98111 11111 please")
        self.say(self.sc, "Mail me ramesh@example.com")
        page = self.bc.get(f"/enquiry/{self.e.pk}/?lang=en").content.decode()
        self.assertNotIn("98111 11111", page)
        self.assertNotIn("ramesh@example.com", page)
        self.assertIn("Contact details hidden", page)
        self.assertNotIn(SELLER, page)
        self.assertNotIn(BUYER, self.sc.get(f"/enquiry/{self.e.pk}/").content.decode())
        self.assertEqual(EnquiryMessage.objects.filter(masked=True).count(), 2)
        self.assertTrue(all("98111" not in m.text and "@" not in m.text for m in EnquiryMessage.objects.all()))  # stored masked, not just displayed masked

    def test_accepting_unlocks_both_sides_contacts(self):
        r = self.sc.post(f"/enquiry/{self.e.pk}/accept/")
        self.assertRedirects(r, f"/enquiry/{self.e.pk}/", fetch_redirect_response=False)
        self.e.refresh_from_db()
        self.assertEqual((self.e.status, self.e.unlock_fee_paise), ("accepted", 0))
        self.assertTrue(self.e.unlocked)
        self.assertIn(SELLER, self.bc.get(f"/enquiry/{self.e.pk}/").content.decode())
        self.assertIn(BUYER, self.sc.get(f"/enquiry/{self.e.pk}/").content.decode())
        self.assertEqual(Message.objects.get().template, "enquiry_accepted")  # the buyer is told
        self.say(self.bc, "My number is 98111 11111")
        self.assertIn("98111 11111", EnquiryMessage.objects.last().text)  # no masking once unlocked

    def test_only_the_seller_can_decide_and_only_once(self):
        self.assertEqual(self.bc.post(f"/enquiry/{self.e.pk}/accept/").status_code, 404)
        self.sc.post(f"/enquiry/{self.e.pk}/decline/")
        self.sc.post(f"/enquiry/{self.e.pk}/accept/")
        self.e.refresh_from_db()
        self.assertEqual(self.e.status, "declined")
        self.assertFalse(self.e.unlocked)

    def test_declined_conversations_are_closed_to_new_messages(self):
        self.sc.post(f"/enquiry/{self.e.pk}/decline/")
        self.say(self.bc, "please reconsider")
        self.assertEqual(self.e.messages.count(), 0)
        self.assertNotContains(self.bc.get(f"/enquiry/{self.e.pk}/"), "/message/")

    def test_strangers_cannot_open_or_write_into_a_conversation(self):
        stranger = Client()
        stranger.force_login(make_buyer(BUYER2, name="Other Buyer"))
        self.assertEqual(stranger.get(f"/enquiry/{self.e.pk}/").status_code, 404)
        self.assertEqual(self.say(stranger, "hi").status_code, 404)
        other_farmer = Client()
        other_farmer.force_login(make_farmer("9000000077"))
        self.assertEqual(other_farmer.get(f"/enquiry/{self.e.pk}/").status_code, 404)
        self.assertEqual(Client().get(f"/enquiry/{self.e.pk}/").status_code, 302)

    def test_replies_notify_the_other_side_but_not_every_message(self):
        self.say(self.sc, "Yes, 4 quintal is fine")
        self.say(self.sc, "And I can load on Friday")
        texts = list(Message.objects.filter(template="enquiry_message"))
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].phone, BUYER)

    def test_message_flood_is_limited(self):
        for i in range(services.MAX_MESSAGES_PER_ENQUIRY_PER_HOUR + 5):
            self.say(self.bc, f"hello {i}")
        self.assertEqual(EnquiryMessage.objects.filter(sender=self.buyer).count(), services.MAX_MESSAGES_PER_ENQUIRY_PER_HOUR)

    def test_closing_as_sold_marks_the_listing_sold(self):
        self.sc.post(f"/enquiry/{self.e.pk}/accept/")
        self.sc.post(f"/enquiry/{self.e.pk}/close/", {"sold": "1"})
        self.li.refresh_from_db()
        self.e.refresh_from_db()
        self.assertEqual((self.li.status, self.e.status), ("sold", "closed"))

    def test_a_buyer_closing_does_not_sell_the_listing(self):
        self.bc.post(f"/enquiry/{self.e.pk}/close/", {"sold": "1"})
        self.li.refresh_from_db()
        self.assertEqual(self.li.status, "active")

    def test_accepted_deal_can_be_recorded_in_the_farmer_book_with_fields_prefilled(self):
        self.sc.post(f"/enquiry/{self.e.pk}/accept/")
        page = self.sc.get(f"/enquiry/{self.e.pk}/?lang=en").content.decode()
        self.assertIn(f"/farmer/book/{self.li.source_cycle.client_id}/add/sale/?quantity=4&amp;unit=quintal&amp;rate=2450&amp;channel=direct_buyer&amp;buyer_note=Rao Caterers", page)
        form = self.sc.get(f"/farmer/book/{self.li.source_cycle.client_id}/add/sale/?quantity=4&unit=quintal&rate=2450&channel=direct_buyer&buyer_note=Rao+Caterers").context["form"]
        self.assertEqual((form.initial["quantity"], form.initial["rate"], form.initial["channel"], form.initial["buyer_note"]), ("4", "2450", "direct_buyer", "Rao Caterers"))

    def test_unread_badges(self):
        self.assertEqual(services.unread_for(self.seller), 1)  # a new enquiry nobody has opened
        self.sc.get(f"/enquiry/{self.e.pk}/")
        self.assertEqual(services.unread_for(self.seller), 0)
        self.say(self.bc, "hello?")
        self.assertEqual(services.unread_for(self.seller), 1)
        self.sc.post(f"/enquiry/{self.e.pk}/accept/")
        self.assertEqual(services.unread_for(self.buyer), 1)
        self.bc.get(f"/enquiry/{self.e.pk}/")
        self.assertEqual(services.unread_for(self.buyer), 0)
        self.assertContains(self.bc.get("/buyer/?lang=en"), 'class="n"') if services.unread_for(self.buyer) else None


class ConsoleMarketTests(MarketCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("9999999999", password="x")
        self.ac = Client()
        self.ac.force_login(self.admin)

    def test_pages_render(self):
        self.listing()
        for lang in ("hi", "mr", "en"):
            for path in ("/console/listings/", "/console/buyers/", "/console/messages/", "/console/rates/"):
                self.assertEqual(self.ac.get(f"{path}?lang={lang}").status_code, 200, path)

    def test_admin_can_hide_and_restore_a_listing(self):
        li = self.listing()
        self.ac.post(f"/console/listings/{li.pk}/visibility/", {"hide": "1"})
        self.assertEqual(len(Client().get("/market/").context["rows"]), 0)
        self.assertContains(self.sc.get(f"/farmer/sell/{li.pk}/?lang=en"), "has hidden this listing")
        self.ac.post(f"/console/listings/{li.pk}/visibility/", {"hide": "0"})
        self.assertEqual(len(Client().get("/market/").context["rows"]), 1)

    def test_admin_verifies_a_buyer_and_sellers_see_the_badge(self):
        bp = self.buyer.buyer_profile
        bp.gstin = "27AAAAA0000A1Z5"
        bp.save()
        self.ac.post(f"/console/buyers/{bp.pk}/verify/", {"verified": "1"})
        bp.refresh_from_db()
        self.assertEqual(bp.level, 2)
        li = self.listing()
        services.start_enquiry(self.buyer, li, Decimal("2"), None, "")
        self.assertContains(self.sc.get(f"/farmer/sell/{li.pk}/?lang=en"), "✔")

    def test_non_staff_cannot_use_console_actions(self):
        li = self.listing()
        self.sc.post(f"/console/listings/{li.pk}/visibility/", {"hide": "1"})
        li.refresh_from_db()
        self.assertEqual(li.status, "active")

    def test_rates_page_says_when_the_feed_is_not_connected(self):
        self.assertContains(self.ac.get("/console/rates/?lang=en"), "Connect the government price feed")

    def test_refresh_button_starts_a_fetch(self):
        from unittest import mock
        with mock.patch("rates.ingest.run_update") as run, override_settings(DATA_GOV_IN_API_KEY="k"):
            self.ac.post("/console/rates/refresh/")
            import time
            time.sleep(0.2)
        run.assert_called_once()


class BuyerHomeTests(MarketCase):
    def test_dashboard_shows_new_produce_and_counts(self):
        li = self.listing()
        services.start_enquiry(self.buyer, li, Decimal("2"), None, "")
        page = self.bc.get("/buyer/?lang=en").content.decode()
        self.assertIn("Wheat", page)
        self.assertIn("Open conversations", page)

    def test_new_buyer_is_pointed_at_the_profile(self):
        c = Client()
        c.force_login(make_buyer("9866666666", complete=False))
        self.assertContains(c.get("/buyer/?lang=en"), "Tell us about your business")

    def test_home_page_shows_fresh_listings(self):
        self.listing()
        self.assertContains(Client().get("/?lang=en"), "Fresh from farmers")
