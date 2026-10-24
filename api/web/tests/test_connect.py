"""Sessions and the two-device rule, notifications, the weather alarm banner, shared ad cards and voice notes."""
import io
import json
from datetime import timedelta

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import LoginSession, SitePolicy, User
from engagement.models import ShareCard, VoiceConsent, VoiceNote
from notify.models import Preference
from weather.models import Alert
from web.tests.test_market_web import NOTIFY_MEM, make_farmer
from web.tests.test_web import FARMER, WebCase, staff, web_login


class SessionPolicyTests(WebCase):
    def test_a_third_device_signs_out_the_oldest(self):
        devices = [Client() for _ in range(3)]
        for c in devices:
            web_login(c)
        user = User.objects.get(phone=FARMER)
        self.assertEqual(LoginSession.objects.filter(user=user, ended_at__isnull=True).count(), 2)
        self.assertTrue(devices[0].get("/farmer/")["Location"].startswith("/login/"))  # the oldest was signed out
        self.assertEqual(devices[2].get("/notifications/").status_code, 200)

    def test_staff_change_the_limit_in_the_console(self):
        sc = Client()
        sc.force_login(staff())
        sc.post("/console/settings/", {"max_sessions": "1", "session_days": "30"})
        self.assertEqual(SitePolicy.current().max_sessions, 1)
        self.assertEqual(sc.get("/console/sessions/?lang=en").status_code, 200)


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class NotifyTests(TestCase):
    def setUp(self):
        self.farmer = make_farmer()
        self.c = Client()
        self.c.force_login(self.farmer)

    def test_preferences_are_saved(self):
        self.assertEqual(self.c.get("/notifications/settings/?lang=en").status_code, 200)
        self.c.post("/notifications/settings/", {"alarm_sound": "", "whatsapp": "1", "sms": "1"})
        p = Preference.objects.get(user=self.farmer)
        self.assertEqual((p.alarm_sound, p.whatsapp), (False, True))

    def test_app_files_are_served_without_signing_in(self):
        anon = Client()
        self.assertTrue(json.loads(anon.get("/manifest.webmanifest").content)["start_url"].startswith("/"))
        r = anon.get("/sw.js")
        self.assertEqual(r["Service-Worker-Allowed"], "/")


class AlertBannerTests(TestCase):
    def test_critical_alert_shows_in_red_with_the_alarm_and_can_be_acknowledged(self):
        farmer = make_farmer()
        a = Alert.objects.create(farmer=farmer, crop="wheat", stage="flowering", kind="frost", severity="critical", day=timezone.localdate(), advice="Frost tonight.")
        c = Client()
        c.force_login(farmer)
        page = c.get("/farmer/?lang=en").content.decode()
        self.assertIn("wx-banner", page)
        self.assertIn("alarm.js", page)
        c.post("/weather/seen/", {"alert": str(a.pk)})
        a.refresh_from_db()
        self.assertIsNotNone(a.acknowledged_at)
        self.assertNotIn("wx-banner", c.get("/farmer/?lang=en").content.decode())


class ShareTests(TestCase):
    def setUp(self):
        self.farmer = make_farmer()
        self.c = Client()
        self.c.force_login(self.farmer)

    def png(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (60, 60), "green").save(buf, "PNG")
        buf.seek(0)
        buf.name = "card.png"
        return buf

    def test_achievement_card_upload_and_public_landing(self):
        r = json.loads(self.c.post("/share/new/", {"kind": "achievement"}).content)
        code = r["code"]
        self.assertIn(f"/s/{code}/", r["url"])
        self.assertEqual(self.c.post(f"/share/{code}/image/", {"image": self.png()}).status_code, 200)
        anon = Client()
        self.assertEqual(anon.get(f"/s/{code}.png")["Content-Type"], "image/png")
        page = anon.get(f"/s/{code}/?lang=en").content.decode()
        self.assertIn("og:image", page)
        self.assertNotIn('class="side"', page)  # nothing but the card before signing in
        self.assertEqual(ShareCard.objects.get(code=code).views, 1)

    def test_only_real_pngs_and_only_the_owner(self):
        code = json.loads(self.c.post("/share/new/", {"kind": "achievement"}).content)["code"]
        fake = io.BytesIO(b"GIF89a....")
        fake.name = "x.png"
        self.assertEqual(self.c.post(f"/share/{code}/image/", {"image": fake}).status_code, 400)
        other = Client()
        other.force_login(make_farmer("9000000301"))
        self.assertEqual(other.post(f"/share/{code}/image/", {"image": self.png()}).status_code, 404)
        self.assertEqual(self.c.post("/share/new/", {"kind": "listing", "ref": "999"}).status_code, 404)


class VoiceTests(TestCase):
    def setUp(self):
        self.farmer = make_farmer()
        self.c = Client()
        self.c.force_login(self.farmer)

    def test_nothing_is_kept_without_consent_and_withdrawing_deletes_everything(self):
        self.assertEqual(self.c.post("/voice/save/", {"text": "गेहूँ में पीला रतुआ", "language": "hi-IN"}).status_code, 403)
        self.c.post("/voice/agree/", {"keep_audio": "0"})
        r = json.loads(self.c.post("/voice/save/", {"text": "गेहूँ में पीला रतुआ दिख रहा है, क्या दवा डालें", "language": "hi-IN"}).content)
        self.assertIn("wheat", r["crops"])
        self.assertEqual(VoiceNote.objects.count(), 1)
        self.c.post("/voice/withdraw/")
        self.assertEqual((VoiceNote.objects.count(), VoiceConsent.objects.count()), (0, 0))
