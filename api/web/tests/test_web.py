import re

from django.test import Client, TestCase, override_settings

from accounts.messaging import MemoryBackend
from accounts.models import AuditEvent, Role, User, UserStatus
from accounts.tests.helpers import last_code
from farmerbook.models import CropCycle, Expense, Harvest, Sale
from profiles.models import FarmerProfile, OrgLinkRequest, Organisation, OrgMembership
from web import strings
from web.models import Lead
from web.translations import TRANSLATIONS

FARMER = "9876543210"
AGENT = "9811111111"


def web_login(client, phone=FARMER, door="farmer"):
    """Sign in through the website exactly as a person would: number, code, (first time) consent."""
    client.get(f"/login/?as={door}&lang=en")
    client.post("/login/", {"phone": phone})
    r = client.post("/login/verify/", {"code": last_code(phone)})
    if r.status_code == 302 and r["Location"] == "/login/consent/":
        r = client.post("/login/consent/", {"consent": "on"})
    return r


def staff():
    return User.objects.create_superuser("9999999999", password="x")


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend", OTP_RESEND_COOLDOWN_SECONDS=0)
class WebCase(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.client = Client()


class TranslationTests(TestCase):
    def test_every_string_has_hindi_and_marathi(self):
        missing = sorted(s for s in strings.all_strings() if s not in TRANSLATIONS)
        self.assertEqual(missing, [], "Add these to web/translations.py")

    def test_placeholders_match(self):
        for en, (hi, mr) in TRANSLATIONS.items():
            ph = set(re.findall(r"\{\w+\}", en))
            self.assertEqual(set(re.findall(r"\{\w+\}", hi)), ph, en)
            self.assertEqual(set(re.findall(r"\{\w+\}", mr)), ph, en)

    def test_no_apostrophes_that_would_break_javascript(self):
        self.assertNotIn("'", TRANSLATIONS["Remove this entry?"][0] + TRANSLATIONS["Remove this entry?"][1])


class PublicPageTests(WebCase):
    PAGES = ["/", "/for-farmers/", "/for-fpos/", "/for-buyers/", "/calculator/", "/privacy/", "/login/"]

    def test_pages_render_in_all_languages(self):
        for lang in ("hi", "mr", "en"):
            for path in self.PAGES:
                r = self.client.get(f"{path}?lang={lang}")
                self.assertEqual(r.status_code, 200, (path, lang))
                self.assertContains(r, f'<html lang="{lang}">')

    def test_final_taglines(self):
        self.assertContains(self.client.get("/?lang=hi"), "सीधा बाज़ार, सही दाम, अपना किसान भाई")
        self.assertContains(self.client.get("/?lang=mr"), "थेट बाजार, योग्य भाव, आपला शेतकरी भाऊ")

    def test_language_choice_is_remembered(self):
        self.client.get("/?lang=mr")
        self.assertContains(self.client.get("/for-farmers/"), '<html lang="mr">')

    def test_default_language_is_hindi(self):
        self.assertContains(self.client.get("/"), '<html lang="hi">')

    def test_health_and_api_still_work(self):
        self.assertEqual(self.client.get("/health/").status_code, 200)
        self.assertEqual(self.client.get("/api/me").status_code, 401)


class LeadTests(WebCase):
    VALID = {"name": "Asha", "phone": "98 7654 3210", "city": "Pune", "consent": "on", "website": ""}

    def test_buyer_lead_saved_with_attribution(self):
        self.client.get("/for-buyers/?utm_source=facebook&utm_campaign=kodo")
        r = self.client.post("/lead/buyer/", self.VALID)
        self.assertRedirects(r, "/thanks/?kind=buyer", fetch_redirect_response=False)
        lead = Lead.objects.get()
        self.assertEqual((lead.kind, lead.phone), ("buyer", "9876543210"))
        self.assertEqual(lead.attribution["utm_source"], "facebook")

    def test_attribution_keeps_first_touch(self):
        self.client.get("/?utm_source=google")
        self.client.get("/?utm_source=facebook")
        self.client.post("/lead/fpo/", self.VALID)
        self.assertEqual(Lead.objects.get().attribution["utm_source"], "google")

    def test_honeypot_is_dropped_quietly(self):
        r = self.client.post("/lead/buyer/", {**self.VALID, "website": "http://spam"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Lead.objects.count(), 0)

    def test_needs_consent_and_valid_phone(self):
        self.assertEqual(self.client.post("/lead/buyer/", {**self.VALID, "consent": ""}).status_code, 200)
        self.assertEqual(self.client.post("/lead/buyer/", {**self.VALID, "phone": "123"}).status_code, 200)
        self.assertEqual(Lead.objects.count(), 0)

    def test_flood_from_one_address_is_limited(self):
        for _ in range(12):
            self.client.post("/lead/buyer/", self.VALID)
        self.assertEqual(Lead.objects.count(), 10)

    def test_calculator_lead_keeps_numbers(self):
        self.client.post("/lead/calculator/", {**self.VALID, "payload": '{"crop": "wheat", "result": {"gap": 8460}}'})
        self.assertEqual(Lead.objects.get().payload["result"]["gap"], 8460)

    def test_unknown_kind_goes_home(self):
        self.assertEqual(self.client.get("/lead/whatever/").status_code, 302)


class SignInTests(WebCase):
    def test_new_farmer_signs_up_through_consent(self):
        r = web_login(self.client)
        self.assertRedirects(r, "/farmer/", fetch_redirect_response=False)
        u = User.objects.get(phone=FARMER)
        self.assertEqual((u.role, u.status), (Role.FARMER, UserStatus.ACTIVE))
        self.assertTrue(u.consented_at)
        self.assertEqual(self.client.get("/farmer/").status_code, 200)

    def test_returning_farmer_skips_consent(self):
        web_login(self.client)
        self.client.post("/logout/")
        self.client.post("/login/", {"phone": FARMER})
        r = self.client.post("/login/verify/", {"code": last_code(FARMER)})
        self.assertRedirects(r, "/farmer/", fetch_redirect_response=False)

    def test_consent_step_cannot_be_skipped(self):
        self.client.post("/login/", {"phone": FARMER})
        self.client.post("/login/verify/", {"code": last_code(FARMER)})
        self.assertEqual(self.client.post("/login/consent/", {}).status_code, 200)
        self.assertEqual(self.client.get("/farmer/").status_code, 302)
        self.assertFalse(User.objects.filter(phone=FARMER).exists())

    def test_consent_page_needs_a_verified_code(self):
        self.assertRedirects(self.client.get("/login/consent/"), "/login/", fetch_redirect_response=False)
        self.client.post("/login/", {"phone": FARMER})
        self.assertRedirects(self.client.get("/login/consent/"), "/login/", fetch_redirect_response=False)

    def test_wrong_code_is_refused_and_five_burn_it(self):
        self.client.post("/login/", {"phone": FARMER})
        for _ in range(5):
            r = self.client.post("/login/verify/", {"code": "000000"})
            self.assertEqual(r.status_code, 200)
        r = self.client.post("/login/verify/", {"code": last_code(FARMER)})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(phone=FARMER).exists())

    def test_request_reply_does_not_reveal_registered_numbers(self):
        web_login(self.client)
        other = Client()
        a = other.post("/login/", {"phone": FARMER})
        b = other.post("/login/", {"phone": "9123456789"})
        self.assertEqual((a.status_code, a["Location"]), (b.status_code, b["Location"]))

    def test_bad_number_shows_error(self):
        self.client.get("/login/?lang=en")
        r = self.client.post("/login/", {"phone": "12345"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "10-digit")

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=30)
    def test_resend_respects_cooldown(self):
        self.client.get("/login/?lang=en")
        self.client.post("/login/", {"phone": FARMER})
        r = self.client.post("/login/resend/", follow=True)
        self.assertContains(r, "seconds")

    def test_assisted_farmer_confirms_and_becomes_active(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", verified=True)
        agent = User.objects.create_user(AGENT, role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        from profiles import services
        services.create_assisted_farmer(agent, {"phone": FARMER, "name": "Ramesh", "village": "N", "district": "Rewa", "land_acres": "2", "crops": ["wheat"]}, org=org)
        self.assertEqual(User.objects.get(phone=FARMER).status, UserStatus.PENDING)
        web_login(self.client)
        u = User.objects.get(phone=FARMER)
        self.assertEqual(u.status, UserStatus.ACTIVE)
        self.assertEqual(u.farmer_profile.org_status, "confirmed")
        self.assertEqual(u.farmer_profile.level, 2)

    def test_logout_ends_session(self):
        web_login(self.client)
        self.client.post("/logout/")
        self.assertEqual(self.client.get("/farmer/").status_code, 302)
        self.assertTrue(AuditEvent.objects.filter(action="logout").exists())

    def test_logout_is_post_only(self):
        web_login(self.client)
        self.assertEqual(self.client.get("/logout/").status_code, 405)

    def test_language_follows_the_account(self):
        web_login(self.client)
        self.client.get("/farmer/?lang=mr")
        self.assertEqual(User.objects.get(phone=FARMER).language, "mr")

    def test_each_door_lands_in_its_own_area(self):
        web_login(self.client, AGENT, door="fpo")
        self.assertEqual(User.objects.get(phone=AGENT).role, Role.AGENT)
        r = self.client.get("/farmer/")
        self.assertRedirects(r, "/fpo/", fetch_redirect_response=False)

    def test_farmer_number_cannot_become_fpo(self):
        web_login(self.client)
        self.client.post("/logout/")
        r = web_login(self.client, FARMER, door="fpo")
        self.assertRedirects(r, "/farmer/", fetch_redirect_response=False)
        self.assertEqual(User.objects.get(phone=FARMER).role, Role.FARMER)


class AccessTests(WebCase):
    def test_anonymous_goes_to_login(self):
        for path in ("/farmer/", "/farmer/book/", "/fpo/", "/console/", "/buyer/"):
            self.assertRedirects(self.client.get(path), "/login/", fetch_redirect_response=False)

    def test_wrong_role_goes_home(self):
        web_login(self.client)
        for path in ("/fpo/", "/console/", "/buyer/"):
            self.assertRedirects(self.client.get(path), "/farmer/", fetch_redirect_response=False)

    def test_console_is_staff_only_even_for_agents(self):
        web_login(self.client, AGENT, door="fpo")
        self.assertRedirects(self.client.get("/console/"), "/fpo/", fetch_redirect_response=False)

    def test_buyer_can_save_business_details(self):
        web_login(self.client, "9822222222", door="buyer")
        self.assertEqual(self.client.get("/buyer/").status_code, 200)
        self.assertEqual(self.client.get("/buyer/profile/").status_code, 200)
        r = self.client.post("/buyer/profile/", {"contact_name": "Sita", "business_name": "Sita Caterers", "business_type": "caterer", "city": "Pune", "gstin": "", "fssai": ""})
        self.assertRedirects(r, "/buyer/", fetch_redirect_response=False)
        self.assertEqual(User.objects.get(phone="9822222222").buyer_profile.level, 1)


class FarmerFlowTests(WebCase):
    def setUp(self):
        super().setUp()
        web_login(self.client)
        self.user = User.objects.get(phone=FARMER)

    def crop(self):
        r = self.client.post("/farmer/book/new/", {"crop": "wheat", "field_name": "Home field", "area_acres": "2", "season": "rabi", "sowing_date": "2026-11-01", "expected_harvest_date": "2027-03-20"})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return CropCycle.objects.get(owner=self.user)

    def add(self, c, kind, data, ok=True):
        r = self.client.post(f"/farmer/book/{c.client_id}/add/{kind}/", data)
        self.assertEqual(r.status_code, 302 if ok else 200, getattr(r, "context", None) and r.context["form"].errors)
        return r

    def test_next_step_walks_a_new_farmer_forward(self):
        self.assertContains(self.client.get("/farmer/"), "/farmer/profile/")
        self.client.post("/farmer/profile/", {"name": "Ramesh", "village": "Naigarhi", "district": "Rewa", "land_acres": "3.5", "crops": ["wheat"], "other_crops": "kodo"})
        self.assertEqual(self.user.farmer_profile.level, 1)
        self.assertEqual(self.user.farmer_profile.crops, ["wheat", "kodo"])
        self.assertContains(self.client.get("/farmer/"), "/farmer/fpo/")

    def test_profile_needs_a_crop(self):
        r = self.client.post("/farmer/profile/", {"name": "R", "village": "V", "district": "D", "land_acres": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.user.farmer_profile.level, 0)

    def test_crop_creates_field_cycle_and_harvest_reminder(self):
        c = self.crop()
        self.assertEqual(c.plot.name, "Home field")
        self.assertEqual(c.activities.filter(kind="harvest", done=False).count(), 1)
        self.assertContains(self.client.get("/farmer/"), "Coming up")

    def test_other_crop_needs_a_name(self):
        r = self.client.post("/farmer/book/new/", {"crop": "other", "field_name": "F", "area_acres": "1"})
        self.assertEqual(r.status_code, 200)

    def test_profit_is_worked_out_by_the_server(self):
        c = self.crop()
        self.add(c, "expense", {"category": "seed", "amount": "3000", "date": "2026-11-01"})
        self.add(c, "harvest", {"quantity": "20", "unit": "quintal", "date": "2027-03-25", "grade": "A"})
        self.add(c, "sale", {"quantity": "10", "unit": "quintal", "rate": "2400", "date": "2027-04-01", "channel": "direct_buyer"})
        s = Sale.objects.get()
        self.assertEqual((str(s.quantity_kg), str(s.amount)), ("1000.000", "24000.00"))
        page = self.client.get(f"/farmer/book/{c.client_id}/").content.decode()
        self.assertIn("₹21,000", page)  # profit 24000 - 3000
        self.assertEqual(CropCycle.objects.get().status, "harvested")

    def test_cannot_sell_more_than_harvested(self):
        c = self.crop()
        self.add(c, "harvest", {"quantity": "5", "unit": "quintal", "date": "2027-03-25"})
        r = self.add(c, "sale", {"quantity": "6", "unit": "quintal", "rate": "2400", "date": "2027-04-01", "channel": "mandi"}, ok=False)
        self.assertContains(r, "in stock")
        self.assertEqual(Sale.objects.count(), 0)

    def test_bags_need_a_weight(self):
        c = self.crop()
        self.add(c, "harvest", {"quantity": "10", "unit": "bag", "date": "2027-03-25"}, ok=False)
        self.add(c, "harvest", {"quantity": "10", "unit": "bag", "bag_weight_kg": "50", "date": "2027-03-25"})
        self.assertEqual(str(Harvest.objects.get().quantity_kg), "500.000")

    def test_reminder_can_be_marked_done(self):
        c = self.crop()
        self.add(c, "task", {"kind": "spray", "date": "2026-12-20", "planned": "on"})
        t = c.activities.get(kind="spray")
        self.assertFalse(t.done)
        self.client.post(f"/farmer/book/{c.client_id}/done/{t.client_id}/")
        t.refresh_from_db()
        self.assertTrue(t.done)

    def test_delete_is_soft_and_blocked_when_it_would_hide_sold_stock(self):
        c = self.crop()
        self.add(c, "harvest", {"quantity": "5", "unit": "quintal", "date": "2027-03-25"})
        self.add(c, "sale", {"quantity": "5", "unit": "quintal", "rate": "2000", "date": "2027-04-01", "channel": "mandi"})
        h = Harvest.objects.get()
        self.client.post(f"/farmer/book/{c.client_id}/delete/harvest/{h.client_id}/")
        h.refresh_from_db()
        self.assertIsNone(h.deleted_at)
        s = Sale.objects.get()
        self.client.post(f"/farmer/book/{c.client_id}/delete/sale/{s.client_id}/")
        self.client.post(f"/farmer/book/{c.client_id}/delete/harvest/{h.client_id}/")
        h.refresh_from_db()
        self.assertIsNotNone(h.deleted_at)

    def test_one_farmer_cannot_open_anothers_book(self):
        c = self.crop()
        other = Client()
        web_login(other, "9123456789")
        self.assertEqual(other.get(f"/farmer/book/{c.client_id}/").status_code, 404)
        self.assertEqual(other.post(f"/farmer/book/{c.client_id}/add/expense/", {"category": "seed", "amount": "5", "date": "2026-11-01"}).status_code, 404)
        self.assertEqual(Expense.objects.count(), 0)

    def test_web_and_api_records_are_the_same_data(self):
        from accounts.tests.helpers import authed, login
        from rest_framework.test import APIClient
        c = self.crop()
        self.add(c, "expense", {"category": "labour", "amount": "500", "date": "2026-11-05"})
        tokens = login(APIClient(), FARMER, device="device-web-test-1").data
        r = authed(tokens["access"]).get("/api/farmerbook/expenses")
        self.assertEqual(len(r.data["results"]), 1)

    def test_join_with_code_and_pending_state(self):
        Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", verified=True)
        r = self.client.post("/farmer/fpo/", {"code": "NAIGARHI"})
        self.assertRedirects(r, "/farmer/fpo/", fetch_redirect_response=False)
        self.assertEqual(OrgLinkRequest.objects.get().status, "pending")
        self.assertContains(self.client.get("/farmer/fpo/"), "Naigarhi FPO")

    def test_unknown_code_is_refused(self):
        r = self.client.post("/farmer/fpo/", {"code": "nope"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "No organisation found")

    def test_only_verified_fpos_are_searchable(self):
        Organisation.objects.create(name="Secret FPO", code="secret", verified=False)
        Organisation.objects.create(name="Open FPO", code="open", verified=True)
        page = self.client.get("/farmer/fpo/").content.decode()
        self.assertIn("Open FPO", page)
        self.assertNotIn("Secret FPO", page)

    def test_delete_account_needs_the_word(self):
        self.client.post("/farmer/account/delete/", {"confirm": "no"})
        self.assertEqual(User.objects.get(pk=self.user.pk).status, UserStatus.ACTIVE)
        self.client.post("/farmer/account/delete/", {"confirm": "delete"})
        self.assertEqual(User.objects.get(pk=self.user.pk).status, UserStatus.DELETED)
        self.assertEqual(self.client.get("/farmer/").status_code, 302)

    def test_pages_render_in_marathi(self):
        c = self.crop()
        for path in ("/farmer/", "/farmer/profile/", "/farmer/fpo/", "/farmer/book/", "/farmer/book/new/", f"/farmer/book/{c.client_id}/",
                     f"/farmer/book/{c.client_id}/add/sale/", "/farmer/account/"):
            self.assertEqual(self.client.get(path + "?lang=mr").status_code, 200, path)


class FpoFlowTests(WebCase):
    def setUp(self):
        super().setUp()
        web_login(self.client, AGENT, door="fpo")
        self.agent = User.objects.get(phone=AGENT)

    def register(self):
        return self.client.post("/fpo/register/", {"contact_name": "Mohan", "name": "Naigarhi Kisan FPO", "kind": "fpo", "district": "Rewa", "block": "Naigarhi", "registration_no": "U123"})

    def test_new_agent_must_register_an_organisation_first(self):
        self.assertRedirects(self.client.get("/fpo/"), "/fpo/register/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get("/fpo/farmers/"), "/fpo/register/", fetch_redirect_response=False)

    def test_registration_creates_unverified_org(self):
        self.assertRedirects(self.register(), "/fpo/", fetch_redirect_response=False)
        org = Organisation.objects.get()
        self.assertFalse(org.verified)
        self.assertEqual(org.code, "naigarhi-kis")
        self.assertTrue(OrgMembership.objects.filter(user=self.agent, organisation=org, role="admin").exists())
        self.assertContains(self.client.get("/fpo/"), "checking your registration")

    def test_unverified_fpo_cannot_add_farmers_or_approve(self):
        self.register()
        r = self.client.post("/fpo/farmers/add/", {"phone": FARMER, "name": "R", "village": "V", "district": "D", "language": "hi"})
        self.assertRedirects(r, "/fpo/", fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(phone=FARMER).exists())

    def test_unverified_agent_is_also_blocked_on_the_json_api(self):
        from accounts.tests.helpers import login
        from rest_framework.test import APIClient
        self.register()
        tokens = login(APIClient(), AGENT, device="device-agent-0001", role="farmer")
        # the existing agent account signs in to the API like anyone else and is still refused
        from profiles.tests.test_profiles import sign_in_as
        r = sign_in_as(self.agent).post("/api/agent/farmers", {"phone": FARMER, "name": "R", "village": "V", "district": "D"}, format="json")
        self.assertEqual((r.status_code, r.data["error"]["code"]), (403, "org_not_verified"))
        self.assertIsNotNone(tokens)

    def verified(self):
        self.register()
        Organisation.objects.update(verified=True)
        return Organisation.objects.get()

    def test_verified_fpo_adds_a_farmer_who_then_confirms(self):
        org = self.verified()
        r = self.client.post("/fpo/farmers/add/", {"phone": "98765 43210", "name": "Ramesh", "village": "Naigarhi", "district": "Rewa", "land_acres": "3", "crops": ["wheat"], "language": "hi"})
        self.assertRedirects(r, "/fpo/farmers/", fetch_redirect_response=False)
        farmer = User.objects.get(phone=FARMER)
        self.assertEqual((farmer.status, farmer.created_by_id), (UserStatus.PENDING, self.agent.pk))
        self.assertIn("OTP", MemoryBackend.outbox[-1]["text"])  # the code goes to the farmer's own phone
        self.assertContains(self.client.get("/fpo/farmers/"), "Ramesh")
        farmer_client = Client()
        web_login(farmer_client)
        farmer.refresh_from_db()
        self.assertEqual(farmer.status, UserStatus.ACTIVE)
        self.assertEqual(farmer.farmer_profile.organisation_id, org.pk)
        self.assertEqual(farmer.farmer_profile.org_status, "confirmed")

    def test_existing_number_is_not_overwritten(self):
        self.verified()
        User.objects.create_user(FARMER, role=Role.FARMER, status=UserStatus.ACTIVE)
        r = self.client.post("/fpo/farmers/add/", {"phone": FARMER, "name": "X", "village": "V", "district": "D", "language": "hi"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already has an account")
        self.assertEqual(FarmerProfile.objects.get().name, "")

    def test_bulk_add_reports_every_line(self):
        self.verified()
        lines = "9876543210, Ramesh, Naigarhi, Rewa, 3.5, wheat kodo\n12345, Bad, V, D\n9811111112, Sita, Gangeo, Rewa"
        r = self.client.post("/fpo/farmers/bulk/", {"lines": lines})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["ok"] for x in r.context["results"]], [True, False, True])
        self.assertEqual(User.objects.filter(status=UserStatus.PENDING).count(), 2)
        self.assertEqual(User.objects.get(phone=FARMER).farmer_profile.crops, ["wheat", "kodo"])

    def test_join_request_is_approved_by_the_fpo(self):
        org = self.verified()
        farmer_client = Client()
        web_login(farmer_client)
        farmer_client.post("/farmer/fpo/", {"code": org.code})
        self.assertContains(self.client.get("/fpo/requests/"), "Approve")
        link = OrgLinkRequest.objects.get()
        self.client.post(f"/fpo/requests/{link.pk}/approve/")
        link.refresh_from_db()
        self.assertEqual(link.status, "approved")
        self.assertEqual(FarmerProfile.objects.get().org_status, "confirmed")

    def test_join_link_signs_the_farmer_up_with_the_fpo(self):
        org = self.verified()
        farmer_client = Client()
        self.assertContains(farmer_client.get(f"/join/{org.code}/"), "Naigarhi Kisan FPO")
        web_login(farmer_client)
        self.assertEqual(OrgLinkRequest.objects.get().status, "pending")

    def test_auto_approve_confirms_link_members_at_once(self):
        org = self.verified()
        self.client.post("/fpo/auto-approve/")
        org.refresh_from_db()
        self.assertTrue(org.auto_approve_members)
        farmer_client = Client()
        farmer_client.get(f"/join/{org.code}/")
        web_login(farmer_client)
        self.assertEqual(FarmerProfile.objects.get().org_status, "confirmed")
        self.assertEqual(OrgLinkRequest.objects.get().status, "approved")

    def test_join_link_for_unverified_or_unknown_fpo_is_404(self):
        self.register()
        self.assertEqual(Client().get("/join/naigarhi-kis/").status_code, 404)
        self.assertEqual(Client().get("/join/nothing/").status_code, 404)

    def test_an_fpo_only_sees_its_own_farmers(self):
        self.verified()
        other = Organisation.objects.create(name="Other FPO", code="other", verified=True)
        u = User.objects.create_user("9000000009", role=Role.FARMER, status=UserStatus.ACTIVE)
        fp = u.farmer_profile
        fp.name, fp.organisation, fp.org_status = "Someone Else", other, "confirmed"
        fp.save()
        self.assertNotContains(self.client.get("/fpo/farmers/"), "Someone Else")

    def test_dashboard_summarises_members_and_share_link(self):
        org = self.verified()
        r = self.client.get("/fpo/")
        self.assertContains(r, f"/join/{org.code}/")
        self.assertContains(r, "wa.me")
        r = self.client.get("/fpo/?lang=mr")
        self.assertEqual(r.status_code, 200)

    def test_pages_render_in_all_languages(self):
        self.verified()
        for lang in ("hi", "mr", "en"):
            for path in ("/fpo/", "/fpo/farmers/", "/fpo/farmers/add/", "/fpo/farmers/bulk/", "/fpo/requests/"):
                self.assertEqual(self.client.get(f"{path}?lang={lang}").status_code, 200, path)


class ConsoleTests(WebCase):
    def setUp(self):
        super().setUp()
        self.admin = staff()
        self.client.force_login(self.admin)

    def test_pages_render(self):
        Organisation.objects.create(name="A", code="a")
        for lang in ("hi", "mr", "en"):
            for path in ("/console/", "/console/orgs/", "/console/orgs/new/", "/console/farmers/", "/console/farmers/add/", "/console/leads/", "/console/audit/"):
                self.assertEqual(self.client.get(f"{path}?lang={lang}").status_code, 200, path)

    def test_admin_approves_an_fpo_from_the_overview(self):
        org = Organisation.objects.create(name="Waiting FPO", code="waiting")
        self.assertContains(self.client.get("/console/"), "Waiting FPO")
        self.client.post(f"/console/orgs/{org.pk}/verify/", {"verified": "1", "back": "/console/"})
        org.refresh_from_db()
        self.assertTrue(org.verified)
        self.assertTrue(AuditEvent.objects.filter(action="org_verified", actor=self.admin).exists())

    def test_admin_creates_fpo_with_agent_who_can_then_work(self):
        r = self.client.post("/console/orgs/new/", {"contact_name": "Mohan", "name": "Gangeo FPO", "kind": "fpo", "district": "Rewa", "block": "", "registration_no": "", "agent_phone": "98111 11111", "verified": "on"})
        self.assertRedirects(r, "/console/orgs/", fetch_redirect_response=False)
        org = Organisation.objects.get()
        self.assertTrue(org.verified)
        agent = User.objects.get(phone=AGENT)
        self.assertEqual(agent.role, Role.AGENT)
        agent_client = Client()
        web_login(agent_client, AGENT, door="fpo")
        self.assertEqual(agent_client.get("/fpo/").status_code, 200)
        self.assertEqual(agent_client.post("/fpo/farmers/add/", {"phone": FARMER, "name": "R", "village": "V", "district": "D", "language": "hi"}).status_code, 302)

    def test_agent_number_cannot_reuse_a_farmers_number(self):
        User.objects.create_user(AGENT, role=Role.FARMER, status=UserStatus.ACTIVE)
        r = self.client.post("/console/orgs/new/", {"contact_name": "M", "name": "X FPO", "kind": "fpo", "district": "Rewa", "agent_phone": AGENT})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Organisation.objects.count(), 0)

    def test_admin_adds_a_farmer_for_any_fpo(self):
        org = Organisation.objects.create(name="Unverified FPO", code="unv")
        r = self.client.post("/console/farmers/add/", {"organisation": org.pk, "phone": FARMER, "name": "Ramesh", "village": "V", "district": "Rewa", "language": "mr"})
        self.assertRedirects(r, "/console/farmers/", fetch_redirect_response=False)
        farmer = User.objects.get(phone=FARMER)
        self.assertEqual((farmer.status, farmer.language, farmer.farmer_profile.organisation_id), (UserStatus.PENDING, "mr", org.pk))

    def test_leads_list_and_csv(self):
        Lead.objects.create(kind="buyer", name="Asha", phone="9876543210", attribution={"utm_source": "facebook"})
        self.assertContains(self.client.get("/console/leads/"), "Asha")
        csv = self.client.get("/console/leads/?format=csv")
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("facebook", csv.content.decode())

    def test_non_staff_cannot_post_to_console(self):
        org = Organisation.objects.create(name="A", code="a")
        c = Client()
        web_login(c)
        c.post(f"/console/orgs/{org.pk}/verify/", {"verified": "1"})
        org.refresh_from_db()
        self.assertFalse(org.verified)


class CsrfTests(TestCase):
    def test_forms_reject_posts_without_a_token(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post("/login/", {"phone": FARMER}).status_code, 403)
        self.assertEqual(c.post("/lead/buyer/", {}).status_code, 403)


class VoiceTests(WebCase):
    def test_every_page_carries_the_listen_helper_in_its_language(self):
        for path in ("/", "/login/", "/rates/", "/calculator/", "/market/", "/privacy/"):
            for lang in ("hi", "mr", "en"):
                r = self.client.get(f"{path}?lang={lang}")
                self.assertContains(r, 'id="sb-voice"', msg_prefix=path)
                self.assertContains(r, "web/voice.js", msg_prefix=path)
        import json

        body = self.client.get("/?lang=hi").content.decode()
        cfg = json.loads(re.search(r'<script id="sb-voice" type="application/json">(.*?)</script>', body, re.S).group(1))
        self.assertEqual(cfg["speech"], "hi-IN")
        self.assertEqual(cfg["t"]["Read this screen"], "यह स्क्रीन पढ़कर सुनाएँ")
        self.assertContains(self.client.get("/?lang=mr"), "mr-IN")

    def test_login_shows_trial_code_for_farmers_only(self):
        with override_settings(OTP_STATIC_CODE="123456", OTP_BACKEND="accounts.messaging.MemoryBackend"):
            self.client.post("/login/", {"phone": "9222222222", "channel": "sms"})
            self.assertContains(self.client.get("/login/verify/?lang=en"), "123456")
            User.objects.create_user(phone="9222222223", role=Role.ADMIN)
            self.client.post("/login/", {"phone": "9222222223", "channel": "sms"})
            self.assertNotContains(self.client.get("/login/verify/?lang=en"), "123456")
