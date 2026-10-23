import json
import shutil
import subprocess
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import unittest
from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.messaging import MemoryBackend as OtpMemory
from accounts.models import Role, User, UserStatus
from notify.backends import MemoryBackend
from notify.models import Message
from profiles.models import FarmerProfile
from rates import calc
from rates.geocode import GeocodeError
from rates.models import MarketRate, MspPrice, RateAlert
from web import rate_alerts
from web.tests.test_web import FARMER, web_login

NOTIFY_MEM = {"sms": "notify.backends.MemoryBackend", "whatsapp": "notify.backends.MemoryBackend"}
TODAY = timezone.localdate()


def rate(crop="wheat", state="Madhya Pradesh", district="Rewa", market="Rewa", modal=2400, days_ago=0, source="agmarknet", commodity=None):
    return MarketRate.objects.create(source=source, date=TODAY - timedelta(days=days_ago), state=state, district=district, market=market,
                                     commodity=commodity or crop.title(), variety="Other", crop=crop, min_price=modal - 100, max_price=modal + 100, modal_price=modal)


def farmer_user(phone=FARMER, district="", state="Madhya Pradesh", complete=False):
    u = User.objects.create_user(phone, role=Role.FARMER, status=UserStatus.ACTIVE, consent_version="2026-10-v1")
    fp = u.farmer_profile
    fp.state, fp.district = state, district
    if complete:
        fp.name, fp.village, fp.district, fp.land_acres, fp.crops = "Ramesh Kushwaha", "Naigarhi", district or "Rewa", 3, ["wheat"]
    fp.save()
    return u


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend", OTP_RESEND_COOLDOWN_SECONDS=0, RATES_SHOW_DEMO=False, NOTIFY_BACKENDS=NOTIFY_MEM)
class RatesWebCase(TestCase):
    def setUp(self):
        cache.clear()
        OtpMemory.outbox.clear()
        MemoryBackend.outbox.clear()
        self.client = Client()


def viewer(client):
    """Everything is behind sign-in now; a buyer is the plainest signed-in visitor."""
    client.force_login(User.objects.create_user("9800000001", role=Role.BUYER, status=UserStatus.ACTIVE, consent_version="2026-10-v1"))


class LocationTests(RatesWebCase):
    def setUp(self):
        super().setUp()
        viewer(self.client)

    def resolve(self, client=None, lat=24.5362, lon=81.3037):
        return (client or self.client).post("/location/resolve/", json.dumps({"lat": lat, "lon": lon}), content_type="application/json")

    def test_a_shared_position_becomes_a_district_in_the_session(self):
        rate()
        with mock.patch("rates.geocode.reverse", return_value=("Madhya Pradesh", "Rewa")):
            r = self.resolve()
        self.assertEqual(r.json(), {"ok": True, "state": "Madhya Pradesh", "district": "Rewa", "label": "Rewa, Madhya Pradesh"})
        self.assertEqual(self.client.session["loc"]["district"], "Rewa")
        self.assertNotIn("lat", self.client.session["loc"])  # coordinates are never kept

    def test_map_names_are_matched_to_mandi_names(self):
        rate(district="Rewa")
        with mock.patch("rates.geocode.reverse", return_value=("Madhya Pradesh", "Rewa District")):
            self.assertEqual(self.resolve().json()["district"], "Rewa")

    def test_failures_are_reported_not_raised(self):
        for code in ("outside_india", "unavailable", "not_found"):
            with mock.patch("rates.geocode.reverse", side_effect=GeocodeError(code)):
                self.assertEqual(self.resolve().json(), {"ok": False, "error": code})

    def test_bad_input_and_get_are_refused(self):
        self.assertEqual(self.client.post("/location/resolve/", "nonsense", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/location/resolve/", json.dumps({"lat": "x", "lon": 1}), content_type="application/json").status_code, 400)
        self.assertEqual(self.client.get("/location/resolve/").status_code, 405)

    def test_lookups_are_rate_limited_per_address(self):
        with mock.patch("rates.geocode.reverse", return_value=("Madhya Pradesh", "Rewa")):
            codes = [self.resolve().status_code for _ in range(32)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30:], [429, 429])

    def test_empty_farmer_profile_gets_the_district(self):
        u = farmer_user()
        self.client.force_login(u)
        with mock.patch("rates.geocode.reverse", return_value=("Madhya Pradesh", "Rewa")):
            self.resolve()
        u.farmer_profile.refresh_from_db()
        self.assertEqual(u.farmer_profile.district, "Rewa")

    def test_a_typed_district_is_never_overwritten(self):
        u = farmer_user(district="Satna")
        self.client.force_login(u)
        with mock.patch("rates.geocode.reverse", return_value=("Madhya Pradesh", "Rewa")):
            self.resolve()
        u.farmer_profile.refresh_from_db()
        self.assertEqual(u.farmer_profile.district, "Satna")

    def test_choosing_by_hand_only_accepts_known_places(self):
        rate()
        ok = self.client.post("/location/choose/", json.dumps({"state": "Madhya Pradesh", "district": "Rewa"}), content_type="application/json")
        self.assertEqual(ok.json()["label"], "Rewa, Madhya Pradesh")
        bad = self.client.post("/location/choose/", json.dumps({"state": "Madhya Pradesh", "district": "Atlantis"}), content_type="application/json")
        self.assertEqual(bad.status_code, 400)

    def test_signed_in_farmers_location_comes_from_their_profile(self):
        rate()
        self.client.force_login(farmer_user(district="Rewa"))
        self.assertContains(self.client.get("/rates/?lang=en"), "Rewa, Madhya Pradesh")

    def test_location_needs_sign_in(self):
        self.assertEqual(Client().post("/location/resolve/", json.dumps({"lat": 24.5, "lon": 81.3}), content_type="application/json").status_code, 302)
        self.assertNotContains(Client().get("/login/?lang=en"), "Allow location to see rates near you")


class LoginNextTests(RatesWebCase):
    def test_returns_to_a_local_page_after_signing_in(self):
        self.client.get("/login/?as=farmer&lang=en&next=/calculator/")
        self.client.post("/login/", {"phone": FARMER})
        self.client.post("/login/verify/", {"code": __import__("accounts.tests.helpers", fromlist=["x"]).last_code(FARMER)})
        r = self.client.post("/login/consent/", {"consent": "on"})
        self.assertRedirects(r, "/calculator/", fetch_redirect_response=False)

    def test_outside_addresses_are_ignored(self):
        for bad in ("https://evil.example/", "//evil.example/", "javascript:alert(1)", "evil"):
            c = Client()
            c.get("/login/", {"as": "farmer", "lang": "en", "next": bad})
            r = web_login(c)
            self.assertEqual(r["Location"], "/farmer/", bad)


@override_settings(RATES_SHOW_DEMO=True)
class RatesPageTests(RatesWebCase):
    def setUp(self):
        super().setUp()
        viewer(self.client)

    def test_page_shows_prices_msp_and_the_sample_warning(self):
        rate(source="demo", modal=2450)
        MspPrice.objects.create(crop="wheat", name="Wheat", season="RMS 2027-28", price_per_quintal=2610, announced_on=TODAY)
        r = self.client.get("/rates/?lang=en&crop=wheat")
        self.assertContains(r, "₹2,450")
        self.assertContains(r, "₹2,610")
        self.assertContains(r, "Sample data, not real prices")

    def test_empty_state_explains_itself(self):
        self.assertContains(self.client.get("/rates/?lang=en"), "Mandi rates will appear here soon.")

    def test_pages_render_in_every_language(self):
        rate(modal=2400)
        rate(market="Satna", district="Satna", modal=2500)
        for lang in ("hi", "mr", "en"):
            for path in ("/rates/", "/rates/?crop=wheat", "/calculator/", "/", "/alerts/"):
                self.assertIn(self.client.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").status_code, (200, 302), (path, lang))

    def test_home_strip_and_json_endpoints(self):
        rate(modal=2450)
        self.assertContains(self.client.get("/rates/?lang=en"), "₹2,450")
        q = self.client.get("/rates/quote/", {"crop": "wheat", "state": "Madhya Pradesh", "district": "Rewa"}).json()
        self.assertEqual((q["typical"], q["scope"]), (2450, "district"))
        self.assertEqual(self.client.get("/rates/quote/", {"crop": "nope"}).status_code, 400)
        self.assertEqual(self.client.get("/rates/summary/", {"state": "Madhya Pradesh"}).json()["crops"][0]["crop"], "wheat")
        self.assertEqual(self.client.get("/rates/places/").json()["places"], {"Madhya Pradesh": ["Rewa"]})


class AlertTests(RatesWebCase):
    def post(self, client, crop="wheat", channel="whatsapp"):
        return client.post("/rates/alert/", json.dumps({"crop": crop, "channel": channel}), content_type="application/json")

    def test_needs_sign_in(self):
        self.assertEqual(self.post(self.client).status_code, 302)

    def test_subscribe_list_and_remove(self):
        u = farmer_user(district="Rewa")
        self.client.force_login(u)
        r = self.post(self.client)
        self.assertEqual(r.json(), {"ok": True, "live": True})  # the test backend delivers
        self.post(self.client)  # twice is one alert
        self.assertEqual(RateAlert.objects.count(), 1)
        self.assertContains(self.client.get("/alerts/?lang=en"), "Wheat")
        self.client.post(f"/alerts/{RateAlert.objects.get().pk}/delete/")
        self.assertEqual(RateAlert.objects.count(), 0)

    def test_nobody_can_remove_someone_elses_alert(self):
        a = RateAlert.objects.create(user=farmer_user("9111111111"), crop="wheat")
        self.client.force_login(farmer_user("9222222222"))
        self.assertEqual(self.client.post(f"/alerts/{a.pk}/delete/").status_code, 404)

    def test_bad_crop_or_channel(self):
        self.client.force_login(farmer_user())
        self.assertEqual(self.post(self.client, crop="gold").status_code, 400)
        self.assertEqual(self.post(self.client, channel="pigeon").status_code, 400)

    def test_default_backend_is_honest_about_not_delivering(self):
        self.client.force_login(farmer_user())
        with override_settings(NOTIFY_BACKENDS={"sms": "notify.backends.LogBackend", "whatsapp": "notify.backends.LogBackend"}):
            self.assertEqual(self.post(self.client).json()["live"], False)

    def test_daily_message_goes_out_once_with_the_days_price(self):
        rate(modal=2450)
        u = farmer_user(district="Rewa")
        RateAlert.objects.create(user=u, crop="wheat", state="Madhya Pradesh", district="Rewa", channel="sms", language="en")
        self.assertEqual(rate_alerts.send_daily_alerts(), 1)
        self.assertEqual(rate_alerts.send_daily_alerts(), 0)  # not twice in a day
        m = Message.objects.get()
        self.assertIn("₹2,450", m.text)
        self.assertEqual((m.phone, m.channel, m.related), (u.phone, "sms", "rate_alert"))

    def test_stale_or_missing_prices_are_never_sent_as_todays(self):
        RateAlert.objects.create(user=farmer_user(), crop="wheat", state="Madhya Pradesh", channel="sms")
        self.assertEqual(rate_alerts.send_daily_alerts(), 0)  # no data
        rate(days_ago=5)
        self.assertEqual(rate_alerts.send_daily_alerts(), 0)  # too old
        self.assertEqual(Message.objects.count(), 0)

    def test_msp_is_added_when_known(self):
        rate(modal=2450)
        MspPrice.objects.create(crop="wheat", name="Wheat", season="RMS 2027-28", price_per_quintal=2610, announced_on=TODAY)
        RateAlert.objects.create(user=farmer_user(), crop="wheat", state="Madhya Pradesh", channel="sms", language="en")
        rate_alerts.send_daily_alerts()
        self.assertIn("MSP: ₹2,610", Message.objects.get().text)


unittest_skip_no_node = unittest.skipUnless(shutil.which("node"), "node is not installed")

SAMPLE = {"crop": "wheat", "qty": 20, "unit": "quintal", "rate": 2400, "rateUnit": "quintal", "commissionPct": 2, "fees": 300, "other": 0, "transport": 1200}


class CalculatorTests(RatesWebCase):
    def send(self, client, channel="whatsapp", **inputs):
        return client.post("/calculator/send/", json.dumps({"channel": channel, "inputs": {**SAMPLE, **inputs}}), content_type="application/json")

    def test_python_arithmetic_matches_the_sample(self):
        r = calc.compute({**SAMPLE, "directRate": 2800, "directTransport": 2000})
        self.assertEqual((r["hand"], r["cut"], r["direct"], r["gap"]), (Decimal("45540.00"), Decimal("1260.00"), Decimal("54000.00"), Decimal("8460.00")))

    def test_bags_kilos_and_junk(self):
        self.assertEqual(calc.compute({"qty": 40, "unit": "bag", "bagKg": 50, "rate": 24, "rateUnit": "kg"})["gross"], Decimal("48000.00"))
        self.assertEqual(calc.compute({"qty": "abc", "rate": -5})["hand"], Decimal("0.00"))

    @unittest_skip_no_node
    def test_the_browser_and_server_sums_agree(self):
        script = Path(__file__).resolve().parents[1] / "static/web/calculator.js"
        cases = [{**SAMPLE, "directRate": 2800, "directTransport": 2000}, {"qty": 40, "unit": "bag", "bagKg": 50, "rate": 24, "rateUnit": "kg", "commissionPct": 1.5, "fees": 120},
                 {"qty": 1500, "unit": "kg", "rate": 2210, "commissionPct": 3, "transport": 450.5, "directRate": 2300}, {"qty": 2.5, "unit": "tonne", "rate": 18, "rateUnit": "kg", "other": 99}]
        js = subprocess.run(["node", "-e", f"const {{sbCompute}}=require({json.dumps(str(script))});console.log(JSON.stringify({json.dumps(cases)}.map(sbCompute)))"], capture_output=True, text=True, check=True)
        for case, from_js in zip(cases, json.loads(js.stdout)):
            py = calc.compute(case)
            for key in ("gross", "commission", "cut", "hand", "direct", "gap"):
                if key in py or key in from_js:
                    self.assertAlmostEqual(float(py[key]), from_js[key], delta=0.011, msg=f"{key} for {case}")

    def test_page_carries_crops_prices_and_translations(self):
        rate(modal=2450)
        viewer(self.client)
        r = self.client.get("/calculator/?lang=hi&crop=wheat&qty=12&unit=kg")
        data = json.loads(r.content.decode().split('id="calc-data" type="application/json">')[1].split("</script>")[0])
        wheat = next(c for c in data["crops"] if c["crop"] == "wheat")
        self.assertEqual(wheat["typical"], 2450)
        self.assertEqual(data["preset"], {"crop": "wheat", "qty": "12", "unit": "kg"})
        self.assertEqual(data["strings"]["Your result"], "आपका नतीजा")
        self.assertEqual(data["speech"], "hi-IN")
        self.assertTrue(data["user"]["in"])

    def test_sending_needs_a_signed_in_phone(self):
        r = self.send(self.client)
        self.assertEqual((r.status_code, r["Location"]), (302, "/login/"))

    def test_message_uses_server_side_numbers_not_the_browsers(self):
        self.client.force_login(farmer_user())
        r = self.send(self.client, hand=999999999, gross=1)  # extra fields are ignored
        self.assertEqual(r.json()["delivered"], True)
        m = Message.objects.get()
        self.assertEqual((m.phone, m.channel, m.related, m.template), (FARMER, "whatsapp", "calculator", "calc_result"))
        self.assertIn("₹45,540", m.text)
        self.assertNotIn("999999999", m.text)

    def test_direct_comparison_uses_the_longer_message(self):
        self.client.force_login(farmer_user())
        self.send(self.client, directRate=2800, directTransport=2000)
        m = Message.objects.get()
        self.assertEqual(m.template, "calc_result_direct")
        self.assertIn("₹54,000", m.text)
        self.assertIn("₹8,460", m.text)

    def test_without_a_provider_the_person_still_gets_a_whatsapp_link(self):
        self.client.force_login(farmer_user())
        with override_settings(NOTIFY_BACKENDS={"sms": "notify.backends.LogBackend", "whatsapp": "notify.backends.LogBackend"}):
            d = self.send(self.client).json()
        self.assertEqual((d["ok"], d["delivered"], d["status"]), (True, False, "logged"))
        self.assertTrue(d["wa_url"].startswith(f"https://wa.me/91{FARMER}?text="))
        self.assertTrue(d["sms_url"].startswith(f"sms:{FARMER}?body="))

    @override_settings(NOTIFY_MAX_PER_PHONE_PER_DAY=2)
    def test_the_daily_cap_protects_the_sms_bill(self):
        self.client.force_login(farmer_user())
        results = [self.send(self.client).json() for _ in range(3)]
        self.assertEqual([r["ok"] for r in results], [True, True, False])
        self.assertEqual(results[2]["status"], "blocked")

    def test_bad_requests(self):
        self.client.force_login(farmer_user())
        self.assertEqual(self.send(self.client, channel="pigeon").status_code, 400)
        self.assertEqual(self.send(self.client, crop="gold").status_code, 400)
        self.assertEqual(self.send(self.client, qty=0).status_code, 400)
        self.assertEqual(self.client.post("/calculator/send/", "junk", content_type="application/json").status_code, 400)
        self.assertEqual(Message.objects.count(), 0)

    def test_message_language_follows_the_request(self):
        u = farmer_user()
        self.client.force_login(u)
        self.client.get("/?lang=hi")
        self.send(self.client)
        self.assertIn("सीधा बाज़ार", Message.objects.get().text)
