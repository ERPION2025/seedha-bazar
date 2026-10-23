"""The bell: KVK and Seedha Bazar notices land in one list; permission for phone notifications is asked once, after sign-in."""
from django.test import Client, TestCase, override_settings

from accounts.models import User
from extension import services as ext
from extension.models import Centre
from institution import services as inst
from notify.models import InboxItem, Preference
from web.tests.test_market_web import NOTIFY_MEM, make_buyer, make_farmer


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class BellTests(TestCase):
    def setUp(self):
        self.farmer = make_farmer()
        self.c = Client()
        self.c.force_login(self.farmer)
        self.centre = Centre.objects.create(name="KVK Rewa", state="Madhya Pradesh", districts=["Rewa"])
        self.staff = ext.provision_staff("9811100001", self.centre, "expert")

    def test_a_kvk_notice_rings_the_bell_and_opens(self):
        inst.send_notice(self.centre, self.staff, "farmers", ["Rewa"], "Soil testing camp on Friday at 10 am.")
        item = InboxItem.objects.get(user=self.farmer)
        self.assertEqual((item.kind, item.read_at), ("notice", None))
        page = self.c.get("/farmer/?lang=en").content.decode()
        self.assertIn('class="bell"', page)
        self.assertIn('id="bell-n">1<', page)
        self.assertContains(self.c.get("/notifications/?lang=en"), "Soil testing camp")
        self.assertEqual(self.c.get("/notifications/unread.json").json()["unread"], 1)
        self.c.get(f"/notifications/{item.pk}/")
        item.refresh_from_db()
        self.assertIsNotNone(item.read_at)
        self.assertEqual(self.c.get("/notifications/unread.json").json()["unread"], 0)

    def test_owner_sends_a_system_notice_to_one_audience_without_sms(self):
        from notify.models import Message
        buyer = make_buyer()
        sc = Client()
        sc.force_login(User.objects.create_superuser("9999999999", password="x"))
        sc.post("/console/notices/", {"audience": "farmers", "state": "", "title": "Group farming is here", "text": "Start a crop group with your neighbours.",
                                      "url": "/farmer/groups/"})
        item = InboxItem.objects.get(user=self.farmer)
        self.assertEqual((item.kind, item.title, item.url), ("system", "Group farming is here", "/farmer/groups/"))
        self.assertFalse(InboxItem.objects.filter(user=buyer).exists())
        self.assertFalse(Message.objects.filter(template="system_notice").exists())  # bell and phone only, no SMS
        self.assertRedirects(self.c.get(f"/notifications/{item.pk}/"), "/farmer/groups/", fetch_redirect_response=False)

    def test_kvk_staff_have_the_bell_on_their_own_site(self):
        from issues import services as issue_services
        issue_services.raise_issue(self.farmer, {"description": "Leaves turning yellow", "category": "soil"})
        k = Client(HTTP_HOST="connect.testserver")
        k.force_login(self.staff)
        page = k.get("/?lang=en").content.decode()
        self.assertIn('class="bell"', page)
        item = InboxItem.objects.get(user=self.staff)
        self.assertEqual(item.kind, "issue")
        self.assertTrue(item.url.startswith("/issues/"))  # a path on Institution Connect, not the farmer site
        self.assertContains(k.get("/notifications/?lang=en"), item.text[:30])

    def test_mark_all_read(self):
        inst.send_notice(self.centre, self.staff, "farmers", ["Rewa"], "First notice for farmers.")
        inst.send_notice(self.centre, self.staff, "farmers", ["Rewa"], "Second notice for farmers.")
        self.c.post("/notifications/read-all/")
        self.assertFalse(InboxItem.objects.filter(user=self.farmer, read_at__isnull=True).exists())


class PermissionPromptTests(TestCase):
    def test_asked_after_sign_in_only_and_only_once(self):
        anon = Client()
        self.assertNotIn('id="np"', anon.get("/login/?lang=en").content.decode())  # never on sign-in screens
        k = Client(HTTP_HOST="connect.testserver")
        self.assertNotIn('id="np"', k.get("/login/?lang=en").content.decode())
        farmer = make_farmer()
        c = Client()
        c.force_login(farmer)
        page = c.get("/farmer/?lang=en").content.decode()
        self.assertIn('id="np"', page)
        self.assertIn('"asked": false', page)
        c.post("/notifications/prompt/", {"answer": "no"})
        self.assertEqual(Preference.objects.get(user=farmer).prompt_answer, "no")
        self.assertIn('"asked": true', c.get("/farmer/?lang=en").content.decode())  # not asked again, on any device

    def test_settings_moved_under_the_bell(self):
        c = Client()
        c.force_login(make_farmer())
        self.assertContains(c.get("/notifications/settings/?lang=en"), "Notification settings")
        self.assertContains(c.get("/notifications/?lang=en"), "/notifications/settings/")


class LoaderTests(TestCase):
    SCENES = ("sprout", "wheat", "tarazu", "rain", "sack", "tractor")

    def test_every_screen_carries_the_loader_with_all_scenes(self):
        farmer = make_farmer()
        c = Client()
        c.force_login(farmer)
        k = Client(HTTP_HOST="connect.testserver")
        for client, path in ((Client(), "/login/"), (c, "/farmer/"), (c, "/rates/"), (k, "/login/")):
            page = client.get(f"{path}?lang=hi").content.decode()
            self.assertIn('id="sb-loader"', page, path)
            self.assertIn("web/loader.js", page, path)
            for s in self.SCENES:
                self.assertIn(f'id="ld-{s}"', page, (path, s))
            self.assertIn("एक पल…", page)

    def test_hidden_always_hides_and_motion_can_be_switched_off(self):
        from pathlib import Path
        css = (Path(__file__).resolve().parents[1] / "static" / "web" / "app.css").read_text()
        self.assertIn("[hidden]{display:none!important}", css)  # the notification card and the loader really disappear
        self.assertIn("prefers-reduced-motion", css)
