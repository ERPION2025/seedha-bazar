import json
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User, UserStatus
from engagement import scores
from engagement.models import GamePlay
from extension import geo, scope
from extension import services as ext
from extension.models import Centre, InputOffer, InputRequest
from issues import services as issue_services
from issues.models import Issue
from notify.models import Message
from profiles.models import Organisation, OrgMembership
from web.tests.test_market_web import NOTIFY_MEM, TODAY, make_buyer, make_farmer, stocked_cycle

D = Decimal


def make_centre(**over):
    data = {"name": "KVK Rewa", "state": "Madhya Pradesh", "districts": ["Rewa"], "lat": 24.53, "lon": 81.30, "phone": "07662-000000"}
    data.update(over)
    return Centre.objects.create(**data)


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class GeoTests(TestCase):
    def test_points_fall_in_the_right_district(self):
        self.assertEqual(geo.district_at(24.53, 81.30), ("Madhya Pradesh", "Rewa"))
        self.assertEqual(geo.district_at(18.52, 73.85), ("Maharashtra", "Pune"))
        self.assertEqual(geo.district_at(25.45, 78.57), ("Uttar Pradesh", "Jhansi"))  # a border district lands in its own state
        self.assertIsNone(geo.district_at(51.5, 0))

    def test_district_names_match_however_they_are_written(self):
        self.assertTrue(geo.same_district("Khandwa (East Nimar)", "Khandwa"))
        self.assertTrue(geo.same_district("Narsimhapur", "Narsinghpur"))
        self.assertFalse(geo.same_district("Rewa", "Satna"))
        self.assertTrue(make_centre().covers("Madhya Pradesh", "rewa"))


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class CentreCase(TestCase):
    def setUp(self):
        self.centre = make_centre()
        self.expert = ext.provision_staff("9811100001", self.centre, "expert", "Plant protection")
        self.kc = Client(HTTP_HOST="connect.testserver")  # Institution Connect is its own site
        self.kc.force_login(self.expert)
        self.farmer = make_farmer()
        self.fc = Client()
        self.fc.force_login(self.farmer)


class PortalTests(CentreCase):
    def test_staff_are_agronomists_and_land_on_the_control_centre(self):
        self.assertEqual(self.expert.role, Role.AGRONOMIST)
        self.assertRedirects(self.kc.get("/login/"), "/", fetch_redirect_response=False)
        self.assertRedirects(self.fc.get("/kvk/issues/"), "http://connect.localhost:8000/issues/", fetch_redirect_response=False)  # old links move
        fk = Client(HTTP_HOST="connect.testserver")
        fk.force_login(self.farmer)
        self.assertRedirects(fk.get("/"), "/login/", fetch_redirect_response=False)  # farmers cannot use it
        for lang in ("hi", "mr", "en"):
            for path in ("/", "/issues/", "/offers/", "/farmers/", "/farmers/add/", "/orgs/", "/orgs/add/", "/map/", "/weather/", "/loans/", "/notices/", "/groups/"):
                self.assertEqual(self.kc.get(f"{path}?lang={lang}").status_code, 200, path)

    def test_the_district_picture_adds_up_farmers_stock_and_yields(self):
        stocked_cycle(self.farmer, 10, crop="wheat")
        for phone in ("9000000101", "9000000102"):
            stocked_cycle(make_farmer(phone), 20, crop="wheat")
        p = scope.district_picture(self.centre)
        self.assertEqual((p["farmers"], p["stock_total"]), (3, D("5000")))
        y = p["yields"][0]
        self.assertEqual((y["crop"], y["farmers"]), ("wheat", 3))
        self.assertEqual(scope.district_picture(make_centre(name="Other", districts=["Satna"]))["farmers"], 0)

    def test_individual_books_need_the_farmers_yes(self):
        page = self.kc.get(f"/farmers/{self.farmer.pk}/?lang=en").content.decode()
        self.assertIn("has not chosen to share", page)
        self.fc.post("/farmer/sharing/", {"share": "1"})
        stocked_cycle(self.farmer, 7, crop="wheat")
        page = self.kc.get(f"/farmers/{self.farmer.pk}/?lang=en").content.decode()
        self.assertIn(self.farmer.phone, page)
        self.assertIn("7 quintal", page)
        far = make_farmer("9000000103")
        fp = far.farmer_profile
        fp.district, fp.share_with_extension = "Satna", True
        fp.save()
        self.assertEqual(self.kc.get(f"/farmers/{far.pk}/").status_code, 404)  # outside the geofence

    def test_kvk_door_only_lets_in_registered_centre_staff(self):
        r = Client(HTTP_HOST="connect.testserver").post("/login/?lang=en", {"phone": "9811100099", "channel": "sms"})
        self.assertContains(r, "not registered for a KVK")


class IssueTests(CentreCase):
    def test_a_farmer_raises_an_issue_and_the_districts_centre_is_alerted(self):
        r = self.fc.post("/help/new/", {"category": "pest", "crop": "wheat", "description": "White insects under the leaves", "urgent": "on", "via_voice": "1"})
        i = Issue.objects.get()
        self.assertRedirects(r, f"/help/{i.pk}/", fetch_redirect_response=False)
        self.assertEqual((i.centre, i.district, i.urgent, i.via_voice, i.status), (self.centre, "Rewa", True, True, "open"))
        self.assertTrue(Message.objects.filter(phone=self.expert.phone, template="issue_alert").exists())
        self.kc.post(f"/help/{i.pk}/reply/", {"kind": "advice", "text": "Spray neem oil 5 ml per litre", "status": ""})
        i.refresh_from_db()
        self.assertEqual((i.status, i.assigned_to), ("advised", self.expert))
        self.assertIsNotNone(i.first_response_at)
        self.assertTrue(Message.objects.filter(phone=self.farmer.phone, template="issue_reply").exists())
        self.assertContains(self.fc.get(f"/help/{i.pk}/?lang=en"), "neem oil")
        self.kc.post(f"/help/{i.pk}/reply/", {"kind": "note", "text": "internal: check field next week"})
        self.assertNotContains(self.fc.get(f"/help/{i.pk}/"), "internal: check field")
        self.fc.post(f"/help/{i.pk}/reply/", {"text": "Thank you", "status": "resolved"})
        i.refresh_from_db()
        self.assertEqual(i.status, "resolved")

    def test_voice_notes_are_private_and_type_checked(self):
        note = SimpleUploadedFile("v.webm", b"\x1aE\xdf\xa3fake", content_type="audio/webm")
        self.fc.post("/help/new/", {"category": "disease", "description": "", "voice_note": note})
        i = Issue.objects.get()
        self.assertTrue(i.voice_note)
        self.assertEqual(self.fc.get(f"/help/media/issue/{i.pk}/voice_note/").status_code, 200)
        self.assertEqual(self.kc.get(f"/help/media/issue/{i.pk}/voice_note/").status_code, 200)
        stranger = Client()
        stranger.force_login(make_farmer("9000000104"))
        self.assertEqual(stranger.get(f"/help/media/issue/{i.pk}/voice_note/").status_code, 404)
        bad = SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream")
        self.fc.post("/help/new/", {"category": "other", "description": "test", "voice_note": bad})
        self.assertEqual(Issue.objects.count(), 1)
        i.voice_note.delete(save=False)

    def test_overdue_issues_remind_the_centre_once(self):
        i = issue_services.raise_issue(self.farmer, {"description": "Leaves turning yellow", "category": "soil"})
        Issue.objects.filter(pk=i.pk).update(created_at=timezone.now() - timedelta(hours=30))
        self.assertEqual(issue_services.remind_overdue(), 1)
        self.assertEqual(issue_services.remind_overdue(), 0)

    def test_an_insurance_loss_report_reaches_the_kvk(self):
        from io import StringIO

        from django.core.management import call_command
        from insurance.models import Application, Plan
        call_command("seed_insurance", stdout=StringIO())
        app = Application.objects.create(farmer=self.farmer, plan=Plan.objects.get(scheme="pmfby", season="rabi"), crop="wheat", season="rabi", year=2026,
                                         state="Madhya Pradesh", district="Rewa", area_ha=1, sum_insured=50000, farmer_premium=750, status="enrolled")
        self.fc.post(f"/insurance/{app.pk}/loss/", {"loss_date": TODAY.isoformat(), "cause": "hail", "note": "Half the field flattened"})
        i = Issue.objects.get()
        self.assertEqual((i.category, i.source, i.centre, i.urgent), ("crop_loss", "insurance_loss", self.centre, True))


class InputTests(CentreCase):
    def test_offer_reaches_farmers_in_the_district_who_request_and_get_approved(self):
        r = self.kc.post("/offers/", {"kind": "seed", "name": "Wheat seed HI-1544", "crop": "wheat", "quantity": "500", "unit": "kg", "per_person_limit": "40",
                                          "price": "0", "audience": "all", "valid_until": (TODAY + timedelta(days=10)).isoformat(), "notify": "on"})
        o = InputOffer.objects.get()
        self.assertRedirects(r, "/offers/", fetch_redirect_response=False)
        self.assertTrue(Message.objects.filter(phone=self.farmer.phone, template="input_offer").exists())
        self.assertContains(self.fc.get("/inputs/?lang=en"), "Wheat seed HI-1544")
        self.fc.post(f"/inputs/{o.pk}/ask/", {"quantity": "50"})
        self.assertEqual(InputRequest.objects.count(), 0)  # over the per-person limit
        self.fc.post(f"/inputs/{o.pk}/ask/", {"quantity": "40"})
        req = InputRequest.objects.get()
        self.kc.post(f"/offers/{o.pk}/act/", {"request": req.pk, "action": "approved", "note": "Collect on Monday"})
        req.refresh_from_db()
        self.assertEqual((req.status, o.left), ("approved", D("460")))
        far = make_farmer("9000000105")
        fp = far.farmer_profile
        fp.district = "Satna"
        fp.save()
        self.assertEqual(ext.offers_for(far), [])  # outside the geofence


class MapTests(CentreCase):
    def test_public_map_shows_centres_and_fpos_never_farmers(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True, lat=24.6, lon=81.2)
        d = json.loads(self.fc.get("/map/data/?state=Madhya Pradesh").content)
        self.assertEqual([c["name"] for c in d["centres"]], ["KVK Rewa"])
        self.assertEqual([o["name"] for o in d["orgs"]], ["Naigarhi FPO"])
        self.assertNotIn(self.farmer.phone, json.dumps(d))
        self.assertEqual(self.fc.get("/map/?lang=hi").status_code, 200)
        k = json.loads(self.kc.get("/map/data/").content)
        self.assertIn("Rewa", k["districts"])
        self.assertEqual(k["fpos"][0]["name"], "Naigarhi FPO")

    def test_an_fpo_saves_its_office_location_inside_india_only(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        agent = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        c = Client()
        c.force_login(agent)
        c.post("/fpo/location/", {"lat": "51.5", "lon": "0.1"})
        org.refresh_from_db()
        self.assertIsNone(org.lat)
        c.post("/fpo/location/", {"lat": "24.53", "lon": "81.30"})
        org.refresh_from_db()
        self.assertEqual((org.lat, org.lon), (24.53, 81.3))


class EngagementTests(CentreCase):
    def test_scores_rise_with_use_and_results(self):
        a0 = scores.activity(self.farmer)["score"]
        stocked_cycle(self.farmer, 10, crop="wheat")
        self.assertGreater(scores.activity(self.farmer)["score"], a0)
        p = scores.performance(self.farmer)
        self.assertEqual(len(p["parts"]), 6)
        self.assertEqual(sum(x["of"] for x in p["parts"]), 100)
        self.assertTrue(0 <= p["score"] <= 100)

    def test_games_render_save_capped_points_and_show_the_district_board(self):
        for slug in ("quiz", "price", "season", "pests", "memory", "catch", "water", "market", "sums", "name", "weather", "sow"):
            for lang in ("hi", "mr", "en"):
                self.assertEqual(self.fc.get(f"/games/{slug}/?lang={lang}").status_code, 200, slug)
        r = self.fc.post("/games/quiz/score/", data=json.dumps({"score": 5000, "voice": True}), content_type="application/json")
        self.assertEqual(json.loads(r.content)["points"], 100)
        gp = GamePlay.objects.get()
        self.assertEqual((gp.district, gp.used_voice), ("Rewa", True))
        self.assertContains(self.fc.get("/games/?lang=en"), "Ramesh")
        self.assertEqual(Client().post("/games/quiz/score/", data="{}", content_type="application/json").status_code, 302)  # sign in first
        self.assertEqual(self.fc.get("/games/chess/").status_code, 404)

    def test_insights_page(self):
        for c in (self.fc,):
            for lang in ("hi", "mr", "en"):
                self.assertEqual(c.get(f"/insights/?lang={lang}").status_code, 200)
        self.assertContains(self.fc.get("/insights/?lang=en"), "Activity")


class NavigationTests(CentreCase):
    def test_every_kind_of_user_gets_a_side_menu_and_a_bottom_bar_with_more(self):
        from web.tests.test_web import staff
        sc = Client()
        sc.force_login(staff())
        bc = Client()
        bc.force_login(make_buyer())
        for c, home, item in ((self.fc, "/farmer/", "Ask an expert"), (self.kc, "/", "Problems"), (bc, "/buyer/", "Find producers"), (sc, "/console/", "KVKs")):
            page = c.get(f"{home}?lang=en").content.decode()
            self.assertIn('class="side"', page)
            self.assertIn('class="bnav"', page)
            self.assertIn(">More<", page)
            self.assertIn(item, page)
            self.assertNotIn('class="tabs"', page)
