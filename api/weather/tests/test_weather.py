from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from farmerbook.models import CropCycle, Plot
from notify.models import Message
from weather import rules, services, stages
from weather.models import Alert, Forecast, Place, Run
from web.tests.test_market_web import NOTIFY_MEM, make_farmer

TODAY = date(2026, 12, 15)


def days(**over):
    base = {"date": "2026-12-16", "tmax": 22, "tmin": 9, "rain_mm": 0, "rain_prob": 0, "wind": 8, "gust": 15, "humidity": 60, "code": 1}
    out = []
    for i in range(7):
        d = dict(base, date=(date(2026, 12, 16) + timedelta(days=i)).isoformat())
        if i == 1:
            d.update(over)
        out.append(d)
    return out


class StageTests(TestCase):
    def setUp(self):
        self.f = make_farmer()
        self.plot = Plot.objects.create(owner=self.f, name="P", area_acres=1)

    def cycle(self, crop, sown_days_ago, status="active"):
        return CropCycle.objects.create(owner=self.f, plot=self.plot, crop=crop, sowing_date=TODAY - timedelta(days=sown_days_ago), status=status)

    def test_stages_follow_days_since_sowing(self):
        self.assertEqual(stages.stage_of(self.cycle("wheat", 5), TODAY), "sowing")
        self.assertEqual(stages.stage_of(self.cycle("wheat", 40), TODAY), "growing")
        self.assertEqual(stages.stage_of(self.cycle("wheat", 70), TODAY), "flowering")
        self.assertEqual(stages.stage_of(self.cycle("wheat", 100), TODAY), "filling")
        self.assertEqual(stages.stage_of(self.cycle("wheat", 125), TODAY), "harvest")
        self.assertEqual(stages.stage_of(self.cycle("wheat", 200, "harvested"), TODAY, in_stock=True), "stored")
        self.assertEqual(stages.stage_of(CropCycle.objects.create(owner=self.f, plot=self.plot, crop="wheat"), TODAY), "unknown")
        self.assertEqual(stages.stage_of(self.cycle("mango", 400), TODAY), "orchard")


class RuleTests(TestCase):
    def test_the_same_weather_gives_different_advice_by_stage(self):
        rain = days(rain_mm=40, rain_prob=90)
        self.assertIn("Harvest what is ready", rules.advise("wheat", "harvest", rain)[0]["advice"])
        self.assertIn("Wait to sow", rules.advise("wheat", "sowing", rain)[0]["advice"])
        self.assertIn("covered and off the floor", rules.advise("wheat", "stored", rain)[0]["advice"])

    def test_frost_only_for_sensitive_crops_heat_earlier_for_rabi_at_flowering(self):
        cold = days(tmin=2)
        self.assertEqual([a["kind"] for a in rules.advise("potato", "growing", cold)], ["frost"])
        self.assertEqual(rules.advise("wheat", "growing", cold), [])
        warm = days(tmax=35)
        self.assertEqual([a["kind"] for a in rules.advise("wheat", "flowering", warm)], ["heat"])
        self.assertEqual(rules.advise("maize", "flowering", warm), [])

    def test_blight_and_dry_spell(self):
        self.assertEqual([a["kind"] for a in rules.advise("potato", "growing", days(humidity=92, tmax=20))], ["disease"])
        dry = [dict(d, tmax=35) for d in days()]
        self.assertEqual([a["kind"] for a in rules.advise("soybean", "growing", dry, season="kharif")], ["dry"])
        self.assertEqual(rules.advise("soybean", "growing", dry, season="rabi"), [])


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM, WEATHER_LOOKUP_VILLAGES=False)
class RunTests(TestCase):
    def setUp(self):
        self.f = make_farmer()
        plot = Plot.objects.create(owner=self.f, name="P", area_acres=2)
        CropCycle.objects.create(owner=self.f, plot=plot, crop="potato", sowing_date=timezone.localdate() - timedelta(days=30))

    def test_place_falls_back_to_the_district_centre(self):
        p = services.place_for("Madhya Pradesh", "Rewa", "Naigarhi")
        self.assertEqual(p.source, "district")
        self.assertTrue(24 < p.lat < 25.5 and 81 < p.lon < 82.5)

    def test_daily_run_saves_alerts_and_sends_one_message_per_farmer_once(self):
        fake = days(tmin=2, rain_mm=40, rain_prob=90)
        with mock.patch.object(services, "_get", return_value={"daily": {
                "time": [d["date"] for d in fake], "temperature_2m_max": [d["tmax"] for d in fake], "temperature_2m_min": [d["tmin"] for d in fake],
                "precipitation_sum": [d["rain_mm"] for d in fake], "precipitation_probability_max": [d["rain_prob"] for d in fake],
                "wind_speed_10m_max": [d["wind"] for d in fake], "wind_gusts_10m_max": [d["gust"] for d in fake],
                "relative_humidity_2m_mean": [d["humidity"] for d in fake], "weather_code": [d["code"] for d in fake]}}) as g:
            out = services.run_daily()
            self.assertEqual(out, {"alerts": 2, "messages": 1})
            self.assertEqual(services.run_daily(), {"alerts": 0, "messages": 0})  # same alerts are not sent twice
            self.assertEqual(g.call_count, 1)  # the forecast is cached
        m = Message.objects.get(template="weather_alert")
        self.assertIn("Potato", m.text)
        self.assertEqual(set(Alert.objects.values_list("kind", flat=True)), {"frost", "rain"})
        c = Client()
        c.force_login(self.f)
        for lang in ("hi", "mr", "en"):
            self.assertEqual(c.get(f"/weather/?lang={lang}").status_code, 200)
        self.assertContains(c.get("/farmer/?lang=en"), "Frost is likely tonight")

    def test_runs_once_a_day_after_six(self):
        now = timezone.now().replace(hour=4)
        with mock.patch.object(services, "run_daily", return_value={"alerts": 0, "messages": 0}):
            self.assertFalse(services.due(timezone.make_aware(timezone.datetime(2026, 12, 15, 4, 0))))
            when = timezone.make_aware(timezone.datetime(2026, 12, 15, 7, 0))
            self.assertIsNotNone(services.tick(when))
            self.assertIsNone(services.tick(when))
