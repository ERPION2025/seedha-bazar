from datetime import timedelta
from decimal import Decimal as D

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User, UserStatus
from advisory.models import Advisory
from extension import services as ext
from extension.models import Centre
from extension.tests.test_extension import NOTIFY_MEM, make_centre, make_farmer
from farmerbook.models import CropCycle, Plot
from institution.models import Notice
from notify.models import Message
from profiles.models import OrgMembership, Organisation
from storage.models import Pledge, Warehouse

HOST = "connect.testserver"


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, OTP_BACKEND="accounts.messaging.MemoryBackend")
class InstitutionCase(TestCase):
    def setUp(self):
        self.centre = make_centre()
        self.expert = ext.provision_staff("9811100001", self.centre, "expert")
        self.kc = Client(HTTP_HOST=HOST)
        self.kc.force_login(self.expert)
        self.farmer = make_farmer()


class SiteTests(InstitutionCase):
    def test_its_own_site_with_only_its_own_menu(self):
        page = self.kc.get("/?lang=en").content.decode()
        for link in ('href="/weather/"', 'href="/loans/"', 'href="/farmers/"', 'href="/orgs/"', 'href="/offers/"', 'href="/notices/"', 'href="/groups/"'):
            self.assertIn(link, page)
        for farmer_item in ('href="/farmer/book/"', 'href="/rates/"', 'href="/market/"', 'href="/games/"', "Sell"):
            self.assertNotIn(farmer_item, page)
        self.assertIn("portal-kvk", page)
        self.assertEqual(self.kc.get("/farmer/").status_code, 404)  # the main site's pages do not exist here

    def test_sign_in_first_and_only_for_centre_staff(self):
        anon = Client(HTTP_HOST=HOST)
        self.assertTrue(anon.get("/loans/")["Location"].startswith("/login/"))
        page = anon.get("/login/?lang=en").content.decode()
        self.assertIn("Institution Connect sign in", page)
        self.assertNotIn("?as=farmer", page)
        self.assertNotIn('class="side"', page)
        self.assertContains(anon.post("/login/?lang=en", {"phone": self.farmer.phone, "channel": "sms"}), "not registered for a KVK")

    def test_centre_staff_are_sent_to_their_site_from_the_main_one(self):
        main = Client()
        main.get("/login/?as=farmer")
        r = main.post("/login/?lang=en", {"phone": self.expert.phone, "channel": "sms"})
        self.assertContains(r, "belongs to Institution Connect")

    def test_sessions_do_not_cross_sites(self):
        main = Client()
        main.force_login(self.farmer)
        self.assertEqual(main.get("/farmer/").status_code, 200)
        other = Client(HTTP_HOST=HOST)
        other.cookies = main.cookies  # even with the same cookie, a farmer is turned away
        self.assertRedirects(other.get("/"), "/login/", fetch_redirect_response=False)


class AdviceTests(InstitutionCase):
    def test_publish_reaches_district_farmers_and_shows_on_their_weather_page(self):
        r = self.kc.post("/weather/", {"district": "Rewa", "text": "Spray neem oil on wheat against aphids within 3 days.", "kind": "pest", "severity": "warning",
                                       "crops": ["wheat"], "notify": "on"})
        self.assertRedirects(r, "/weather/", fetch_redirect_response=False)
        a = Advisory.objects.get()
        self.assertEqual((a.source, a.district, a.centre, a.crops), ("kvk", "Rewa", self.centre, ["wheat"]))
        self.assertTrue(Message.objects.filter(phone=self.farmer.phone, template="advisory").exists())
        fc = Client()
        fc.force_login(self.farmer)
        self.assertContains(fc.get("/weather/?lang=en"), "neem oil")

    def test_advice_for_another_district_is_not_shown(self):
        Advisory.objects.create(source="kvk", state="Madhya Pradesh", district="Satna", text="Only for Satna farmers, please.")
        fc = Client()
        fc.force_login(self.farmer)
        self.assertNotContains(fc.get("/weather/?lang=en"), "Only for Satna")


class PeopleTests(InstitutionCase):
    def test_add_a_farmer_in_the_district(self):
        r = self.kc.post("/farmers/add/", {"phone": "9822200001", "name": "Sita Devi", "village": "Gurh", "district": "Rewa", "land_acres": "2", "crops": ["wheat"],
                                           "language": "hi"})
        self.assertRedirects(r, "/farmers/", fetch_redirect_response=False)
        u = User.objects.get(phone="9822200001")
        self.assertEqual((u.role, u.status, u.farmer_profile.district, u.created_by), (Role.FARMER, UserStatus.PENDING, "Rewa", self.expert))

    def test_add_an_fpo_it_vouches_for(self):
        r = self.kc.post("/orgs/add/", {"name": "Gurh Kisan FPO", "kind": "fpo", "district": "Rewa", "contact_name": "Ravi", "agent_phone": "9822200002"})
        org = Organisation.objects.get(name="Gurh Kisan FPO")
        self.assertRedirects(r, f"/orgs/{org.pk}/", fetch_redirect_response=False)
        self.assertTrue(org.verified)
        self.assertTrue(OrgMembership.objects.filter(organisation=org, user__phone="9822200002").exists())

    def test_notice_goes_to_the_chosen_audience(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        agent = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        self.kc.post("/notices/", {"audience": "orgs", "district": "", "text": "Seed distribution meeting at KVK on Friday."})
        n = Notice.objects.get()
        self.assertEqual(n.sent, 1)
        self.assertTrue(Message.objects.filter(phone=agent.phone, template="kvk_notice").exists())
        self.assertFalse(Message.objects.filter(phone=self.farmer.phone, template="kvk_notice").exists())


class LoanTests(InstitutionCase):
    def test_loans_in_the_district_add_up_and_names_need_the_farmers_yes(self):
        plot = Plot.objects.create(owner=self.farmer, name="Home", area_acres=2)
        cycle = CropCycle.objects.create(owner=self.farmer, plot=plot, crop="wheat")
        wh = Warehouse.objects.create(name="Laxmi Warehouse", state="Madhya Pradesh", district="Rewa", wdra_reg_no="123", wdra_status="Active", capacity_mt=1200, source="wdra")
        Pledge.objects.create(farmer=self.farmer, crop_cycle=cycle, product="wheat", quantity_kg=2000, warehouse=wh, status="loan", bank="SBI", loan_amount=40000,
                              due_date=timezone.localdate() - timedelta(days=2))
        page = self.kc.get("/loans/?lang=en").content.decode()
        self.assertIn("₹40,000", page)
        self.assertIn("Laxmi Warehouse", page)
        self.assertNotIn(self.farmer.farmer_profile.name, page)  # not shared
        fp = self.farmer.farmer_profile
        fp.share_with_extension = True
        fp.save()
        self.assertContains(self.kc.get("/loans/?lang=en"), fp.name)
