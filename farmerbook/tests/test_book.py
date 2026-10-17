import uuid
from datetime import date, timedelta

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.messaging import MemoryBackend
from accounts.models import OtpChallenge
from accounts.tests.helpers import authed, login
from farmerbook.models import CropCycle, Plot

B = "/api/farmerbook"


def uid():
    return str(uuid.uuid4())


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class BookTestCase(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.a = authed(login(APIClient(), phone="9876543210", device="device-farm-0001").data["access"])
        self.plot = uid()
        self.cycle = uid()
        self.post("plots", {"client_id": self.plot, "name": "Upper field", "area_acres": "2.5"})
        self.post("cycles", {"client_id": self.cycle, "plot": self.plot, "crop": "kodo", "season": "kharif"})

    def post(self, what, body, client=None):
        return (client or self.a).post(f"{B}/{what}", body, format="json")

    def harvest(self, qty="10", unit="quintal", **kw):
        return self.post("harvests", {"client_id": uid(), "crop_cycle": self.cycle, "date": "2026-10-01", "quantity": qty, "unit": unit, **kw})

    def sale(self, qty="4", unit="quintal", rate="3000", **kw):
        return self.post("sales", {"client_id": uid(), "crop_cycle": self.cycle, "date": "2026-10-05", "quantity": qty, "unit": unit, "rate": rate, **kw})


class CrudAndOwnership(BookTestCase):
    def test_create_list_update_delete_plot(self):
        r = self.a.get(f"{B}/plots")
        self.assertEqual(len(r.data["results"]), 1)
        p = self.a.patch(f"{B}/plots/{self.plot}", {"name": "Lower field"}, format="json")
        self.assertEqual(p.data["name"], "Lower field")
        self.assertEqual(self.a.delete(f"{B}/plots/{self.plot}").status_code, 204)
        self.assertEqual(self.a.get(f"{B}/plots").data["results"], [])
        self.assertEqual(self.a.get(f"{B}/plots/{self.plot}").status_code, 404)

    def test_other_farmer_cannot_see_or_touch_records(self):
        MemoryBackend.outbox.clear()
        other = authed(login(APIClient(), phone="9111111111", device="device-farm-0002").data["access"])
        self.assertEqual(other.get(f"{B}/plots").data["results"], [])
        self.assertEqual(other.get(f"{B}/plots/{self.plot}").status_code, 404)
        self.assertEqual(other.patch(f"{B}/plots/{self.plot}", {"name": "x"}, format="json").status_code, 404)
        self.assertEqual(other.delete(f"{B}/plots/{self.plot}").status_code, 404)

    def test_cannot_attach_to_someone_elses_cycle(self):
        MemoryBackend.outbox.clear()
        other = authed(login(APIClient(), phone="9111111111", device="device-farm-0002").data["access"])
        r = self.post("expenses", {"client_id": uid(), "crop_cycle": self.cycle, "category": "seed", "amount": "500", "date": "2026-07-01"}, client=other)
        self.assertEqual(r.status_code, 400)

    def test_buyer_and_anonymous_blocked(self):
        self.assertEqual(APIClient().get(f"{B}/plots").status_code, 401)
        MemoryBackend.outbox.clear()
        buyer = authed(login(APIClient(), phone="9333333333", device="device-buyr-0001", role="buyer").data["access"])
        self.assertEqual(buyer.get(f"{B}/plots").status_code, 403)
        self.assertEqual(buyer.get(f"{B}/ledger").status_code, 403)

    def test_delete_plot_cascades_to_cycle_and_records(self):
        self.harvest()
        self.a.delete(f"{B}/plots/{self.plot}")
        self.assertEqual(self.a.get(f"{B}/cycles").data["results"], [])
        self.assertEqual(self.a.get(f"{B}/harvests").data["results"], [])


class OfflineSync(BookTestCase):
    def test_create_retry_is_idempotent(self):
        cid = uid()
        body = {"client_id": cid, "name": "Back field", "area_acres": "1"}
        self.assertEqual(self.post("plots", body).status_code, 201)
        self.assertEqual(self.post("plots", body).status_code, 200)
        self.assertEqual(Plot.objects.filter(client_id=cid).count(), 1)

    def test_since_returns_changes_and_deletes(self):
        first = self.a.get(f"{B}/plots").data["results"][0]["updated_at"]
        extra = uid()
        self.post("plots", {"client_id": extra, "name": "New", "area_acres": "1"})
        self.a.delete(f"{B}/plots/{self.plot}")
        r = self.a.get(f"{B}/plots", {"since": first})
        by_id = {x["client_id"]: x for x in r.data["results"]}
        self.assertTrue(by_id[self.plot]["deleted"])
        self.assertFalse(by_id[extra]["deleted"])

    def test_bad_since(self):
        self.assertEqual(self.a.get(f"{B}/plots", {"since": "yesterday"}).status_code, 400)

    def test_client_id_cannot_be_changed(self):
        r = self.a.patch(f"{B}/plots/{self.plot}", {"client_id": uid()}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_everything_created_offline_with_client_ids_in_order(self):
        p, c = uid(), uid()
        self.assertEqual(self.post("plots", {"client_id": p, "name": "P2", "area_acres": "1"}).status_code, 201)
        self.assertEqual(self.post("cycles", {"client_id": c, "plot": p, "crop": "wheat"}).status_code, 201)
        r = self.post("harvests", {"client_id": uid(), "crop_cycle": c, "date": "2026-04-01", "quantity": "5", "unit": "quintal"})
        self.assertEqual(r.status_code, 201)

    def test_bad_client_id_text(self):
        r = self.post("plots", {"client_id": "not-a-uuid", "name": "x", "area_acres": "1"})
        self.assertEqual(r.status_code, 400)


class UnitsAndStock(BookTestCase):
    def test_units_convert_to_kg(self):
        self.assertEqual(self.harvest("10", "quintal").data["quantity_kg"], "1000.000")
        self.assertEqual(self.harvest("2", "tonne").data["quantity_kg"], "2000.000")
        self.assertEqual(self.harvest("50", "kg").data["quantity_kg"], "50.000")

    def test_bag_needs_weight(self):
        self.assertEqual(self.harvest("20", "bag").status_code, 400)
        r = self.harvest("20", "bag", bag_weight_kg="40")
        self.assertEqual(r.data["quantity_kg"], "800.000")

    def test_bad_unit_and_quantity(self):
        self.assertEqual(self.harvest("5", "gallon").status_code, 400)
        self.assertEqual(self.harvest("0", "kg").status_code, 400)
        self.assertEqual(self.harvest("-3", "kg").status_code, 400)

    def test_sale_amount_computed_by_server_and_client_cannot_override(self):
        self.harvest("10", "quintal")
        r = self.sale("4", "quintal", "3000", amount="1")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["amount"], "12000.00")
        self.assertEqual(r.data["quantity_kg"], "400.000")

    def test_cannot_sell_more_than_stock(self):
        self.harvest("10", "quintal")
        r = self.sale("11", "quintal")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["code"], "insufficient_stock")
        self.assertEqual(self.sale("10", "quintal").status_code, 201)
        self.assertEqual(self.sale("1", "kg").status_code, 400)

    def test_cannot_shrink_or_delete_harvest_below_sales(self):
        h = self.harvest("10", "quintal").data["client_id"]
        self.sale("8", "quintal")
        r = self.a.patch(f"{B}/harvests/{h}", {"quantity": "5"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["code"], "stock_would_go_negative")
        self.assertEqual(self.a.delete(f"{B}/harvests/{h}").status_code, 400)

    def test_edit_sale_rechecks_stock_without_double_counting_itself(self):
        self.harvest("10", "quintal")
        s = self.sale("8", "quintal").data["client_id"]
        self.assertEqual(self.a.patch(f"{B}/sales/{s}", {"quantity": "9"}, format="json").status_code, 200)
        self.assertEqual(self.a.patch(f"{B}/sales/{s}", {"quantity": "11"}, format="json").status_code, 400)

    def test_deleted_sale_returns_stock(self):
        self.harvest("10", "quintal")
        s = self.sale("10", "quintal").data["client_id"]
        self.a.delete(f"{B}/sales/{s}")
        self.assertEqual(self.sale("10", "quintal").status_code, 201)


class LedgerTests(BookTestCase):
    def test_profit_and_loss(self):
        self.post("expenses", {"client_id": uid(), "crop_cycle": self.cycle, "category": "seed", "amount": "1500.50", "date": "2026-07-01"})
        self.post("expenses", {"client_id": uid(), "crop_cycle": self.cycle, "category": "labour", "amount": "2000", "date": "2026-08-01"})
        self.post("expenses", {"client_id": uid(), "category": "machinery", "amount": "300", "date": "2026-08-02"})  # general
        self.harvest("10", "quintal")
        self.sale("4", "quintal", "3000")
        r = self.a.get(f"{B}/ledger")
        row = r.data["cycles"][0]
        self.assertEqual(row["expenses"], "3500.50")
        self.assertEqual(row["revenue"], "12000.00")
        self.assertEqual(row["profit"], "8499.50")
        self.assertEqual((row["harvested_kg"], row["sold_kg"], row["stock_kg"]), ("1000.000", "400.000", "600.000"))
        self.assertEqual(row["cost_per_kg"], "3.50")
        self.assertEqual(row["avg_sale_rate_per_quintal"], "3000.00")
        self.assertEqual(r.data["general_expenses"], "300.00")
        self.assertEqual(r.data["totals"], {"expenses": "3800.50", "revenue": "12000.00", "profit": "8199.50"})

    def test_deleted_records_excluded_and_empty_cycle_has_no_ratios(self):
        r = self.a.get(f"{B}/ledger")
        row = r.data["cycles"][0]
        self.assertIsNone(row["cost_per_kg"])
        self.assertIsNone(row["avg_sale_rate_per_quintal"])
        e = uid()
        self.post("expenses", {"client_id": e, "crop_cycle": self.cycle, "category": "seed", "amount": "100", "date": "2026-07-01"})
        self.a.delete(f"{B}/expenses/{e}")
        self.assertEqual(self.a.get(f"{B}/ledger").data["cycles"][0]["expenses"], "0.00")

    def test_ledger_is_private(self):
        self.harvest("10", "quintal")
        MemoryBackend.outbox.clear()
        other = authed(login(APIClient(), phone="9111111111", device="device-farm-0002").data["access"])
        self.assertEqual(other.get(f"{B}/ledger").data["cycles"], [])

    def test_stock_endpoint_with_shelf_life(self):
        today = date.today()
        self.harvest("10", "quintal", date=str(today), shelf_life_days=30)
        self.sale("4", "quintal")
        s = self.a.get(f"{B}/stock").data["stock"][0]
        self.assertEqual(s["stock_quintal"], "6.00")
        self.assertEqual(s["days_left"], 30)

    def test_validation_extras(self):
        self.assertEqual(self.post("expenses", {"client_id": uid(), "category": "seed", "amount": "-5", "date": "2026-07-01"}).status_code, 400)
        self.assertEqual(self.post("expenses", {"client_id": uid(), "category": "magic", "amount": "5", "date": "2026-07-01"}).status_code, 400)
        r = self.post("cycles", {"client_id": uid(), "plot": self.plot, "crop": "wheat", "sowing_date": "2026-11-01", "expected_harvest_date": "2026-10-01"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.post("plots", {"client_id": uid(), "name": "x", "area_acres": "0"}).status_code, 400)
