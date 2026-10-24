from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.errors import ApiError
from accounts.messaging import MemoryBackend
from accounts.models import Role, User, UserStatus
from accounts.tests.helpers import last_code
from deals import directory, services
from deals.models import Deal, Payment
from farmerbook.models import Processing
from notify.models import Message
from profiles.models import Organisation, OrgMembership
from web.tests.test_market_web import NOTIFY_MEM, TODAY, make_buyer, make_farmer, stocked_cycle

D = Decimal
SOON = TODAY + timedelta(days=20)


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, OTP_BACKEND="accounts.messaging.MemoryBackend", OTP_RESEND_COOLDOWN_SECONDS=0)
class DealCase(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.farmer = make_farmer()
        fp = self.farmer.farmer_profile
        fp.crops = ["mushroom", "wheat"]
        fp.save()
        self.buyer = make_buyer()
        self.fc, self.bc = Client(), Client()
        self.fc.force_login(self.farmer)
        self.bc.force_login(self.buyer)

    def ask(self, **over):
        data = {"seller": self.farmer, "organisation": None, "product": "dry_mushroom", "source_crop": "mushroom", "quantity": D("20"), "unit": "kg",
                "quality": "Moisture below 10%", "packaging": "bulk", "price": D("900"), "advance_pct": 30, "delivery_by": SOON, "delivery_place": "Pune", "message": "Call me on 9811111111"}
        data.update(over)
        return services.request(self.buyer, data)

    def sign_both(self, deal):
        for who, c in ((self.buyer, self.bc), (self.farmer, self.fc)):
            c.post(f"/deals/{deal.pk}/code/")
            c.post(f"/deals/{deal.pk}/sign/", {"code": last_code(who.phone)})
        deal.refresh_from_db()


class DirectoryTests(DealCase):
    def test_buyers_see_what_farmers_grow_have_and_could_make_but_no_phone(self):
        stocked_cycle(self.farmer, 2, crop="mushroom")
        page = self.bc.get("/buyer/producers/?lang=en").content.decode()
        self.assertIn("Ramesh", page)
        self.assertNotIn("Kushwaha", page)
        self.assertNotIn(self.farmer.phone, page)
        detail = self.bc.get(f"/producers/farmer/{self.farmer.pk}/?lang=en").content.decode()
        self.assertIn("Dried mushroom", detail)  # something they could make from what they grow
        self.assertIn("2 quintal", detail)

    def test_farmers_can_hide_and_others_cannot_browse(self):
        fp = self.farmer.farmer_profile
        fp.discoverable = False
        fp.save()
        self.assertEqual(directory.search(), [])
        self.assertEqual(self.bc.get(f"/producers/farmer/{self.farmer.pk}/").status_code, 404)
        with self.assertRaises(ApiError):
            self.ask()
        self.assertEqual(self.fc.get("/buyer/producers/").status_code, 404)
        self.assertEqual(Client().get("/buyer/producers/").status_code, 302)

    def test_fpo_card_adds_up_member_stock(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        fp = self.farmer.farmer_profile
        fp.organisation, fp.org_status = org, "confirmed"
        fp.save()
        other = make_farmer("9000000055")
        ofp = other.farmer_profile
        ofp.organisation, ofp.org_status = org, "confirmed"
        ofp.save()
        stocked_cycle(self.farmer, 3, crop="wheat")
        stocked_cycle(other, 5, crop="wheat")
        card = directory.fpo_card(org)
        self.assertEqual((card["members"], card["stock"]["wheat"]), (2, D("800")))


class JourneyTests(DealCase):
    def test_the_whole_order_from_request_to_completion(self):
        r = self.bc.post(f"/deals/new/", {"farmer": self.farmer.pk, "product": "dry_mushroom", "quantity": "20", "unit": "kg", "price": "900", "advance_pct": "30",
                                          "delivery_by": SOON.isoformat(), "delivery_place": "Pune", "packaging": "bulk", "note": "Call 9811111111 please"})
        deal = Deal.objects.get()
        self.assertRedirects(r, f"/deals/{deal.pk}/", fetch_redirect_response=False)
        self.assertEqual((deal.status, deal.source_crop, deal.total), ("requested", "mushroom", D("18000")))
        self.assertIn("•••", deal.events.first().text)  # contacts are hidden before signing
        self.assertTrue(Message.objects.filter(phone=self.farmer.phone, template="deal_request").exists())

        page = self.fc.get(f"/deals/{deal.pk}/?lang=en").content.decode()
        self.assertIn("To make this you need about 200 kg of Mushroom", page)  # 20 kg at 10% yield
        self.assertNotIn(self.buyer.phone, page)

        # the seller counters; the buyer cannot accept its own offer, the seller cannot accept its own counter
        self.fc.post(f"/deals/{deal.pk}/counter/", {"quantity": "20", "unit": "kg", "price": "1000", "advance_pct": "40", "delivery_by": SOON.isoformat()})
        self.fc.post(f"/deals/{deal.pk}/accept/")
        deal.refresh_from_db()
        self.assertEqual(deal.status, "negotiating")
        self.bc.post(f"/deals/{deal.pk}/accept/")
        deal.refresh_from_db()
        self.assertEqual((deal.status, deal.price, deal.advance_pct, deal.advance_amount), ("agreed", D("1000"), 40, D("8000")))
        self.assertIn("Rs 1000 per kg", deal.agreement.text)

        # signing needs the code from each person's own phone
        self.bc.post(f"/deals/{deal.pk}/sign/", {"code": "000000"})
        deal.agreement.refresh_from_db()
        self.assertIsNone(deal.agreement.buyer_signed_at)
        self.sign_both(deal)
        self.assertEqual(deal.status, "signed")
        self.assertTrue(deal.agreement.fully_signed)
        self.assertIn(self.buyer.phone, self.fc.get(f"/deals/{deal.pk}/").content.decode())  # contacts unlock

        self.bc.post(f"/deals/{deal.pk}/pay/", {"kind": "advance", "amount": "8000", "method": "upi", "reference": "UTR123"})
        p = Payment.objects.get()
        self.fc.post(f"/deals/{deal.pk}/received/", {"payment": p.pk})
        deal.refresh_from_db()
        self.assertEqual(deal.status, "in_progress")
        self.fc.post(f"/deals/{deal.pk}/progress/", {"text": "Drying started"})
        self.fc.post(f"/deals/{deal.pk}/dispatch/", {"note": "MP17 truck"})
        self.bc.post(f"/deals/{deal.pk}/deliver/", {"received": "19", "ok": "1"})
        deal.refresh_from_db()
        self.assertEqual((deal.status, services.balance_due(deal)), ("delivered", D("11000")))  # 19 kg x 1000 - 8000 advance
        self.bc.post(f"/deals/{deal.pk}/pay/", {"kind": "balance", "amount": "11000", "method": "bank", "reference": "UTR456"})
        self.fc.post(f"/deals/{deal.pk}/received/", {"payment": Payment.objects.get(kind="balance").pk})
        deal.refresh_from_db()
        self.assertEqual(deal.status, "completed")
        self.bc.post(f"/deals/{deal.pk}/rate/", {"stars": "5"})
        deal.refresh_from_db()
        self.assertEqual(deal.buyer_rating, 5)
        self.assertEqual(self.bc.get(f"/deals/{deal.pk}/agreement/?lang=hi").status_code, 200)

    def test_a_payment_the_seller_did_not_get_goes_back(self):
        deal = self.ask()
        self.fc.post(f"/deals/{deal.pk}/accept/")
        deal.refresh_from_db()
        self.sign_both(deal)
        self.bc.post(f"/deals/{deal.pk}/pay/", {"kind": "advance", "amount": "5400"})
        self.fc.post(f"/deals/{deal.pk}/not_received/", {"payment": Payment.objects.get().pk})
        deal.refresh_from_db()
        self.assertEqual(deal.status, "signed")
        self.assertTrue(Payment.objects.get().disputed)

    def test_steps_out_of_order_and_strangers_are_refused(self):
        deal = self.ask()
        self.fc.post(f"/deals/{deal.pk}/dispatch/")
        self.bc.post(f"/deals/{deal.pk}/pay/", {"kind": "advance", "amount": "100"})
        deal.refresh_from_db()
        self.assertEqual((deal.status, Payment.objects.count()), ("requested", 0))
        stranger = Client()
        stranger.force_login(make_buyer("9822222222", name="Other"))
        self.assertEqual(stranger.get(f"/deals/{deal.pk}/").status_code, 404)
        self.assertEqual(stranger.post(f"/deals/{deal.pk}/accept/").status_code, 404)
        with self.assertRaises(ApiError):
            self.ask()  # one open request per product per seller

    def test_bad_terms_are_refused(self):
        for over in ({"price": D("0")}, {"advance_pct": 95}, {"delivery_by": TODAY}, {"product": "gold"}):
            with self.assertRaises(ApiError):
                self.ask(**over)

    def test_an_fpo_agent_handles_requests_to_the_fpo(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        a1 = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        a2 = User.objects.create_user("9833333334", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=a1, organisation=org)
        OrgMembership.objects.create(user=a2, organisation=org)
        deal = self.ask(seller=None, organisation=org, product="wheat", unit="quintal", price=D("2500"))
        self.assertEqual((deal.seller, deal.organisation), (a1, org))
        c2 = Client()
        c2.force_login(a2)
        self.assertEqual(c2.get(f"/deals/{deal.pk}/").status_code, 200)  # any agent of the FPO can act
        c2.post(f"/deals/{deal.pk}/accept/")
        deal.refresh_from_db()
        self.assertEqual(deal.status, "agreed")

    def test_pages_render_in_every_language(self):
        stocked_cycle(self.farmer, 2, crop="mushroom")
        deal = self.ask()
        for c in (self.bc, self.fc):
            for lang in ("hi", "mr", "en"):
                for path in ("/deals/", f"/deals/{deal.pk}/"):
                    self.assertEqual(c.get(f"{path}?lang={lang}").status_code, 200, path)
        for lang in ("hi", "mr", "en"):
            for path in ("/buyer/producers/", f"/producers/farmer/{self.farmer.pk}/", f"/deals/new/?farmer={self.farmer.pk}&product=dry_mushroom"):
                self.assertEqual(self.bc.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").status_code, 200, path)
