from datetime import date, datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from rates import geocode, ingest, services, worker
from rates.crops import CROPS, canonical_crop
from rates.models import GeoCache, MarketRate, MspPrice, RateFetchLog
from rates.sources.datagov import PAGE, DataGovInSource, normalise

TODAY = timezone.localdate()


def rate(crop="wheat", state="Madhya Pradesh", district="Rewa", market="Rewa", modal=2400, days_ago=0, source="agmarknet", commodity=None, variety="Other"):
    return MarketRate.objects.create(
        source=source, date=TODAY - timedelta(days=days_ago), state=state, district=district, market=market, commodity=commodity or crop.title(),
        variety=variety, crop=crop, min_price=Decimal(modal) - 100, max_price=Decimal(modal) + 100, modal_price=Decimal(modal))


class CropNameTests(TestCase):
    def test_agmarknet_names_map_to_our_crops(self):
        cases = {
            "Wheat": "wheat", "Paddy(Dhan)(Common)": "rice", "Soyabean": "soybean", "Bengal Gram(Gram)(Whole)": "gram",
            "Arhar (Tur/Red Gram)(Whole)": "tur", "Green Gram (Moong)(Whole)": "moong", "Black Gram (Urd Beans)(Whole)": "urad",
            "Lentil (Masur)(Whole)": "lentil", "Mustard": "mustard", "Kodo Millet(Kodon)": "kodo", "Jowar(Sorghum)": "jowar",
            "Bajra(Pearl Millet/Cumbu)": "bajra", "Maize": "maize", "Groundnut": "groundnut", "Onion": "onion", "Potato": "potato",
        }
        for name, crop in cases.items():
            self.assertEqual(canonical_crop(name), crop, name)

    def test_things_we_do_not_track_are_left_out(self):
        for name in ("Arhar Dal(Tur Dal)", "Mustard Oil", "Sweet Potato", "Cotton Seed", "Banana", "", "Green Gram Dal (Moong Dal)"):
            self.assertEqual(canonical_crop(name), "", name)

    def test_every_rule_points_at_a_known_crop(self):
        from rates.crops import RULES
        self.assertTrue({k for k, _ in RULES} <= set(CROPS))


class SourceTests(TestCase):
    REC = {"State": "Madhya Pradesh", "District": "Rewa", "Market": "Rewa", "Commodity": "Wheat", "Variety": "Sharbati", "Grade": "FAQ",
           "Arrival_Date": "21/10/2026", "Min_Price": "2300", "Max_Price": "2500", "Modal_Price": "2450"}

    def test_both_field_styles_are_read(self):
        row = normalise(self.REC)
        self.assertEqual((row["date"], row["modal_price"], row["variety"]), (date(2026, 10, 21), Decimal("2450"), "Sharbati"))
        lower = normalise({k.lower(): v for k, v in self.REC.items()})
        self.assertEqual(lower["modal_price"], Decimal("2450"))

    def test_bad_rows_are_dropped(self):
        self.assertIsNone(normalise({**self.REC, "Modal_Price": "NA"}))
        self.assertIsNone(normalise({**self.REC, "Modal_Price": "0"}))
        self.assertIsNone(normalise({**self.REC, "Arrival_Date": "soon"}))
        self.assertIsNone(normalise({**self.REC, "Market": ""}))

    def test_missing_min_and_max_fall_back_to_modal(self):
        row = normalise({**self.REC, "Min_Price": "", "Max_Price": "NA"})
        self.assertEqual((row["min_price"], row["max_price"]), (Decimal("2450"), Decimal("2450")))

    def test_pages_are_followed_until_the_total(self):
        calls = []

        def http(url):
            calls.append(url)
            offset = int(url.split("offset=")[1].split("&")[0])
            n = PAGE if offset == 0 else 5
            return {"total": PAGE + 5, "records": [{**self.REC, "Market": f"M{offset + i}"} for i in range(n)]}

        rows = list(DataGovInSource("key", http=http).fetch())
        self.assertEqual(len(rows), PAGE + 5)
        self.assertEqual(len(calls), 2)
        self.assertIn("api-key=key", calls[0])

    def test_state_filter_is_sent(self):
        urls = []
        list(DataGovInSource("k", ["Maharashtra"], http=lambda u: urls.append(u) or {"total": 0, "records": []}).fetch())
        self.assertIn("filters%5Bstate%5D=Maharashtra", urls[0])


class IngestTests(TestCase):
    ROW = dict(date=TODAY, state="Madhya Pradesh", district="Rewa", market="Rewa", commodity="Wheat", variety="Other", grade="FAQ",
               min_price=Decimal(2300), max_price=Decimal(2500), modal_price=Decimal(2450))

    class Src:
        name = "agmarknet"

        def __init__(self, rows=None, boom=False):
            self.rows, self.boom = rows or [], boom

        def fetch(self):
            if self.boom:
                raise RuntimeError("source is down")
            yield from self.rows

    def test_saves_and_tags_the_crop(self):
        (entry,) = ingest.run_update([self.Src([self.ROW])])
        self.assertEqual((entry.status, entry.rows_saved, entry.latest_date), ("ok", 1, TODAY))
        self.assertEqual(MarketRate.objects.get().crop, "wheat")

    def test_running_twice_updates_instead_of_duplicating(self):
        ingest.run_update([self.Src([self.ROW])])
        ingest.run_update([self.Src([{**self.ROW, "modal_price": Decimal(2500)}])])
        self.assertEqual(MarketRate.objects.count(), 1)
        self.assertEqual(MarketRate.objects.get().modal_price, Decimal("2500"))

    def test_a_failing_source_is_logged_and_does_not_stop_others(self):
        good = self.Src([self.ROW])
        bad = self.Src(boom=True)
        bad.name = "broken"
        logs = ingest.run_update([bad, good])
        self.assertEqual([entry.status for entry in logs], ["failed", "ok"])
        self.assertIn("source is down", logs[0].message)
        self.assertEqual(MarketRate.objects.count(), 1)

    def test_a_source_with_no_rows_counts_as_failed(self):
        (entry,) = ingest.run_update([self.Src([])])
        self.assertEqual(entry.status, "failed")

    @override_settings(DATA_GOV_IN_API_KEY="")
    def test_without_a_key_it_says_so(self):
        (entry,) = ingest.run_update()
        self.assertEqual(entry.status, "skipped")
        self.assertIn("DATA_GOV_IN_API_KEY", entry.message)

    @override_settings(DATA_GOV_IN_API_KEY="")
    def test_command_runs(self):
        out = StringIO()
        call_command("update_rates", stdout=out)
        self.assertIn("skipped", out.getvalue())


@override_settings(RATES_SHOW_DEMO=False)
class QuoteTests(TestCase):
    def test_local_mandis_come_first_and_set_the_typical_price(self):
        rate(district="Rewa", market="Rewa", modal=2400)
        rate(district="Rewa", market="Teonthar", modal=2440)
        rate(district="Satna", market="Satna", modal=2600)
        q = services.quote("wheat", "Madhya Pradesh", "Rewa")
        self.assertEqual(q["scope"], "district")
        self.assertEqual({r["market"] for r in q["local"]}, {"Rewa", "Teonthar"})
        self.assertEqual([r["market"] for r in q["nearby"]], ["Satna"])
        self.assertEqual(q["typical"], Decimal("2420"))

    def test_falls_back_to_the_state_then_to_nothing(self):
        rate(district="Satna", market="Satna", modal=2600)
        q = services.quote("wheat", "Madhya Pradesh", "Rewa")
        self.assertEqual((q["scope"], q["typical"], q["local"]), ("state", Decimal("2600"), []))
        self.assertEqual(services.quote("tur", "Madhya Pradesh", "Rewa")["scope"], "none")
        self.assertIsNone(services.quote("tur")["typical"])

    def test_district_names_are_matched_loosely(self):
        rate(district="Rewa", market="Rewa", modal=2400)
        self.assertEqual(services.quote("wheat", "Madhya Pradesh", "REWA district")["scope"], "state")  # not guessed
        self.assertEqual(services.quote("wheat", "madhya pradesh", "rewa")["scope"], "district")

    def test_only_the_latest_price_per_mandi_counts(self):
        rate(market="Rewa", modal=2300, days_ago=4)
        rate(market="Rewa", modal=2450, days_ago=1)
        q = services.quote("wheat", "Madhya Pradesh", "Rewa")
        self.assertEqual((q["typical"], q["as_of"]), (Decimal("2450"), TODAY - timedelta(days=1)))

    def test_old_prices_are_not_shown_as_current(self):
        rate(days_ago=services.FRESH_DAYS + 3)
        self.assertEqual(services.quote("wheat", "Madhya Pradesh")["scope"], "none")

    def test_several_varieties_take_the_middle_one(self):
        for v, p in (("A", 2300), ("B", 2400), ("C", 3000)):
            rate(variety=v, modal=p)
        self.assertEqual(services.quote("wheat", "Madhya Pradesh", "Rewa")["typical"], Decimal("2400"))

    def test_demo_rows_are_hidden_unless_allowed(self):
        rate(source="demo")
        self.assertEqual(services.quote("wheat", "Madhya Pradesh")["scope"], "none")
        with override_settings(RATES_SHOW_DEMO=True):
            q = services.quote("wheat", "Madhya Pradesh")
            self.assertEqual((q["scope"], q["demo"]), ("state", True))

    def test_msp_is_attached_from_the_newest_announcement(self):
        MspPrice.objects.create(crop="wheat", name="Wheat", season="RMS 2026-27", price_per_quintal=2585, announced_on=date(2025, 10, 1))
        MspPrice.objects.create(crop="wheat", name="Wheat", season="RMS 2027-28", price_per_quintal=2610, announced_on=date(2026, 9, 30))
        rate()
        self.assertEqual(services.quote("wheat", "Madhya Pradesh")["msp"]["price"], Decimal("2610"))

    def test_weekly_trend(self):
        for i in range(3):
            rate(market=f"A{i}", modal=2000, days_ago=7)
            rate(market=f"A{i}", modal=2100, days_ago=1)
        self.assertEqual(services.trend_pct("wheat", "Madhya Pradesh"), Decimal("5.0"))
        self.assertIsNone(services.trend_pct("tur", "Madhya Pradesh"))

    def test_crop_tiles_list_crops_with_prices(self):
        rate("wheat")
        rate("gram", commodity="Bengal Gram(Gram)(Whole)", modal=5600)
        rate("tomato", state="Kerala", district="Idukki", market="Idukki")
        rows = services.crop_prices("Madhya Pradesh", "Rewa")
        self.assertEqual({r["crop"] for r in rows}, {"wheat", "gram"})

    def test_places_and_fuzzy_matching(self):
        rate(district="Rewa")
        rate(state="Maharashtra", district="Pune", market="Pune")
        self.assertEqual(services.places(), {"Madhya Pradesh": ["Rewa"], "Maharashtra": ["Pune"]})
        self.assertEqual(services.match_place("Madhya Pradesh", "Rewa District"), ("Madhya Pradesh", "Rewa"))
        self.assertEqual(services.match_place("Maharashtra", "Pune"), ("Maharashtra", "Pune"))
        self.assertEqual(services.match_place("Goa", "Panaji"), ("", ""))
        self.assertEqual(services.match_place("Madhya Pradesh", "Nowhere"), ("Madhya Pradesh", ""))


class GeocodeTests(TestCase):
    NOMINATIM = {"address": {"state_district": "Rewa", "state": "Madhya Pradesh", "country_code": "in"}}

    def test_resolves_and_caches_to_a_square(self):
        fake = mock.Mock(return_value=self.NOMINATIM)
        with mock.patch("rates.geocode.time.sleep"):
            self.assertEqual(geocode.reverse(24.5362, 81.3037, fetch=fake), ("Madhya Pradesh", "Rewa"))
            self.assertEqual(geocode.reverse(24.5391, 81.3049, fetch=fake), ("Madhya Pradesh", "Rewa"))  # same ~1 km square
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(GeoCache.objects.count(), 1)

    def test_outside_india_is_refused_without_calling_out(self):
        fake = mock.Mock()
        with self.assertRaises(geocode.GeocodeError) as cm:
            geocode.reverse(51.5, -0.12, fetch=fake)
        self.assertEqual(cm.exception.code, "outside_india")
        fake.assert_not_called()

    def test_service_down_is_reported_and_not_cached(self):
        with mock.patch("rates.geocode.time.sleep"), self.assertRaises(geocode.GeocodeError) as cm:
            geocode.reverse(24.5, 81.3, fetch=mock.Mock(side_effect=OSError("timeout")))
        self.assertEqual(cm.exception.code, "unavailable")
        self.assertEqual(GeoCache.objects.count(), 0)

    def test_foreign_result_for_a_border_point_is_refused(self):
        with mock.patch("rates.geocode.time.sleep"), self.assertRaises(geocode.GeocodeError):
            geocode.reverse(27.4, 89.6, fetch=mock.Mock(return_value={"address": {"country_code": "bt", "state": "Thimphu"}}))


class WorkerTests(TestCase):
    NOW = timezone.now()

    def log(self, status, hours_ago):
        e = RateFetchLog.objects.create(source="agmarknet", status=status, started_at=self.NOW - timedelta(hours=hours_ago))
        return e

    @override_settings(DATA_GOV_IN_API_KEY="k")
    def test_schedule(self):
        self.assertTrue(worker.due(self.NOW))  # never fetched
        self.log("ok", 3)
        self.assertFalse(worker.due(self.NOW))  # fetched 3 hours ago
        self.log("ok", 25)  # older, irrelevant
        RateFetchLog.objects.all().delete()
        self.log("ok", 25)
        self.assertTrue(worker.due(self.NOW))  # a day old

    @override_settings(DATA_GOV_IN_API_KEY="k")
    def test_a_failure_is_retried_after_an_hour_not_every_ten_minutes(self):
        self.log("ok", 30)
        self.log("failed", 0.2)
        self.assertFalse(worker.due(self.NOW))
        RateFetchLog.objects.filter(status="failed").delete()
        self.log("failed", 1.5)
        self.assertTrue(worker.due(self.NOW))

    @override_settings(DATA_GOV_IN_API_KEY="")
    def test_no_key_means_never_due(self):
        self.assertFalse(worker.due(self.NOW))

    @override_settings(DATA_GOV_IN_API_KEY="k")
    def test_tick_fetches_then_sends_alerts(self):
        with mock.patch("rates.ingest.run_update", return_value=[RateFetchLog(status="ok")]) as run, \
                mock.patch("web.rate_alerts.send_daily_alerts", return_value=2) as alerts:
            self.assertTrue(worker.tick(self.NOW))
        run.assert_called_once()
        alerts.assert_called_once()


class MspTests(TestCase):
    def test_official_figures_load(self):
        call_command("load_msp", stdout=StringIO())
        call_command("load_msp", stdout=StringIO())  # twice is safe
        self.assertEqual(MspPrice.objects.count(), 25)
        self.assertEqual(MspPrice.objects.get(crop="wheat", season="RMS 2027-28").price_per_quintal, 2610)
        self.assertEqual(MspPrice.objects.get(crop="rice", season="KMS 2026-27").price_per_quintal, 2441)
        self.assertEqual(MspPrice.objects.get(crop="soybean").price_per_quintal, 5708)
        self.assertTrue(set(MspPrice.objects.values_list("crop", flat=True)) <= set(CROPS))


@override_settings(RATES_SHOW_DEMO=False)
class RatesApiTests(TestCase):
    def test_quote_is_public_json(self):
        rate(modal=2400)
        r = self.client.get("/api/rates/", {"crop": "wheat", "state": "Madhya Pradesh", "district": "Rewa"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["typical"], r.json()["scope"], r.json()["unit"]), (2400, "district", "INR per quintal"))

    def test_unknown_crop_is_a_clear_error(self):
        r = self.client.get("/api/rates/", {"crop": "diamonds"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "unknown_crop"))

    def test_places_and_crops(self):
        rate()
        self.assertEqual(self.client.get("/api/rates/places").json()["places"], {"Madhya Pradesh": ["Rewa"]})
        self.assertEqual(self.client.get("/api/rates/crops", {"state": "Madhya Pradesh"}).json()["crops"][0]["crop"], "wheat")
