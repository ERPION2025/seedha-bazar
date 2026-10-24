from datetime import date, timedelta
from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from market import stock
from market.services import save_listing
from notify.models import Message
from storage import services
from storage.models import Pledge, Warehouse
from web.tests.test_market_web import NOTIFY_MEM, make_farmer, stocked_cycle

D = Decimal


class SumsTests(TestCase):
    def test_store_or_sell(self):
        r = services.store_or_sell(D("2000"), D("2000"), 4, D("10"), D("70"), D("7"))
        # 20 q x 2,000 = 40,000; loan 70% = 28,000; storage 20 x 10 x 4 = 800; interest 28,000 x 7% x 4/12 = 653
        self.assertEqual((r["value"], r["loan"], r["storage"], r["interest"]), (D("40000"), D("28000"), D("800"), D("653")))
        self.assertEqual(r["breakeven_q"], D("2073"))


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class PledgeTests(TestCase):
    def setUp(self):
        self.f = make_farmer()
        self.cycle = stocked_cycle(self.f, 30, crop="wheat")
        self.c = Client()
        self.c.force_login(self.f)
        self.wh = Warehouse.objects.create(name="Rewa Central Warehouse", state="Madhya Pradesh", district="Rewa", wdra_reg_no="WDRA-1", verified=True)

    def test_plan_store_borrow_and_repay_with_stock_held_back(self):
        self.assertContains(self.c.get(f"/storage/?line={self.cycle.pk}:wheat&qty=20&price=2000&months=4&lang=en"), "Rewa Central Warehouse")
        self.c.post("/storage/plan/", {"line": f"{self.cycle.pk}:wheat", "qty": "20", "warehouse": self.wh.pk})
        p = Pledge.objects.get()
        self.c.post("/storage/deposit/", {"pledge": p.pk, "enwr": "NERL-123", "deposit_date": "2026-11-01", "repository": "nerl"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.valid_until), ("stored", date(2027, 11, 1)))
        self.assertEqual(stock.free_kg(self.cycle, "wheat"), D("1000"))  # 30 q less the 20 q in the warehouse
        from accounts.errors import ApiError
        with self.assertRaises(ApiError):
            save_listing(self.f, {"crop": "wheat", "quantity": D("15"), "unit": "quintal", "price": D("2500"), "state": "Madhya Pradesh", "district": "Rewa", "source_cycle": self.cycle})
        self.c.post("/storage/loan/", {"pledge": p.pk, "bank": "SBI Rewa", "amount": "28000", "rate": "7", "due_date": (timezone.localdate() + timedelta(days=15)).isoformat()})
        p.refresh_from_db()
        self.assertEqual((p.status, p.loan_amount), ("loan", D("28000")))
        self.assertEqual(services.remind_due(), 1)
        self.assertTrue(Message.objects.filter(template="pledge_due").exists())
        self.c.post("/storage/close/", {"pledge": p.pk})
        self.assertEqual(stock.free_kg(self.cycle, "wheat"), D("3000"))

    def test_cannot_plan_more_than_free_stock(self):
        self.c.post("/storage/plan/", {"line": f"{self.cycle.pk}:wheat", "qty": "31"})
        self.assertEqual(Pledge.objects.count(), 0)

    def test_pages_render(self):
        for c in (self.c, Client()):
            for lang in ("hi", "mr", "en"):
                self.assertEqual(c.get(f"/storage/?lang={lang}").status_code, 200)

    def test_warehouse_csv_loads(self):
        import tempfile
        from io import StringIO

        from django.core.management import call_command
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("name,operator,wdra_reg_no,repository,state,district,address,lat,lon,capacity_mt,commodities,phone\n")
            fh.write("MPWLC Satna,MP Warehousing,WDRA-99,NERL,Madhya Pradesh,Satna,Satna,24.58,80.83,5000,wheat|gram,\n")
        call_command("load_warehouses", fh.name, stdout=StringIO())
        call_command("load_warehouses", fh.name, stdout=StringIO())
        self.assertEqual(Warehouse.objects.filter(wdra_reg_no="WDRA-99").count(), 1)
