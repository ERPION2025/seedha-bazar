from decimal import Decimal

from django.test import Client, TestCase, override_settings

from accounts.models import Role, User, UserStatus
from farmerbook.models import Sale
from market import pools, stock
from market.models import Listing, Pool, PoolShare
from notify.models import Message
from profiles.models import Organisation, OrgMembership
from web.tests.test_market_web import NOTIFY_MEM, make_buyer, make_farmer, stocked_cycle

D = Decimal


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class PoolTests(TestCase):
    def setUp(self):
        self.org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", state="Madhya Pradesh", verified=True)
        self.agent = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=self.agent, organisation=self.org)
        self.ac = Client()
        self.ac.force_login(self.agent)
        self.farmers = []
        for i, q in enumerate((4, 6, 10)):
            f = make_farmer(f"90000002{i:02d}")
            fp = f.farmer_profile
            fp.organisation, fp.org_status = self.org, "confirmed"
            fp.save()
            self.farmers.append((f, stocked_cycle(f, q, crop="wheat")))

    def test_three_small_stocks_become_one_lot_sold_and_shared(self):
        self.ac.post("/fpo/pools/", {"product": "wheat", "unit": "quintal", "price": "2600", "fee_pct": "2", "grade": "A"})
        pool = Pool.objects.get()
        (f1, c1), (f2, c2), (f3, c3) = self.farmers
        self.ac.post(f"/fpo/pools/{pool.pk}/add/", {"cycle": c1.pk, "qty": "4"})  # proposed: the farmer must say yes
        self.assertTrue(Message.objects.filter(phone=f1.phone, template="pool_invite").exists())
        fc = Client()
        fc.force_login(f1)
        fc.post("/farmer/pools/yes/", {"share": PoolShare.objects.get(farmer=f1).pk})
        for f, c, q in ((f2, c2, "6"), (f3, c3, "10")):
            cl = Client()
            cl.force_login(f)
            cl.post("/farmer/pools/join/", {"pool": pool.pk, "cycle": c.pk, "qty": q})
        self.assertEqual(pools.confirmed_kg(pool), D("2000"))
        self.assertEqual(stock.free_kg(c3, "wheat"), D("0"))  # reserved for the lot
        self.ac.post(f"/fpo/pools/{pool.pk}/publish/")
        pool.refresh_from_db()
        li = pool.listing
        self.assertEqual((li.quantity, li.organisation, li.status), (D("20.000"), self.org, "active"))
        self.assertContains(Client().get("/market/?lang=en"), "Pooled from 3 farmers")
        # sold 18 q at 2,700; 2% fee -> 2,646 a quintal to members, in proportion 4:6:10
        self.ac.post(f"/fpo/pools/{pool.pk}/settle/", {"sold": "18", "price": "2700", "buyer": "Rao Mills"})
        pool.refresh_from_db()
        self.assertEqual(pool.status, "sold")
        payouts = {s.farmer_id: (s.sold_kg, s.payout) for s in pool.shares.all()}
        self.assertEqual(payouts[f1.pk], (D("360.000"), D("9525.60")))
        self.assertEqual(payouts[f3.pk], (D("900.000"), D("23814.00")))
        sale = Sale.objects.get(owner=f3)
        self.assertEqual((sale.channel, sale.rate, sale.quantity), ("fpo", D("2646.00"), D("9.000")))
        self.assertEqual(stock.free_kg(c3, "wheat"), D("100"))  # 1 q left after the sale, no longer reserved
        self.assertEqual(Listing.objects.get(pk=li.pk).status, "sold")
        for s in pool.shares.all():
            self.ac.post(f"/fpo/pools/{pool.pk}/paid/", {"share": s.pk})
        pool.refresh_from_db()
        self.assertEqual(pool.status, "settled")

    def test_only_members_with_free_stock_can_join(self):
        pool = pools.create(self.agent, self.org, {"product": "wheat", "price": D("2600")})
        outsider = make_farmer("9000000299")
        oc = stocked_cycle(outsider, 5)
        from accounts.errors import ApiError
        with self.assertRaises(ApiError):
            pools.add_share(pool, oc, D("100"), outsider)
        f, c = self.farmers[0]
        with self.assertRaises(ApiError):
            pools.add_share(pool, c, D("500"), f)  # has 400 kg

    def test_pages_render(self):
        pool = pools.create(self.agent, self.org, {"product": "wheat", "price": D("2600")})
        fc = Client()
        fc.force_login(self.farmers[0][0])
        for lang in ("hi", "mr", "en"):
            for c, path in ((self.ac, "/fpo/pools/"), (self.ac, f"/fpo/pools/{pool.pk}/"), (fc, "/farmer/pools/")):
                self.assertEqual(c.get(f"{path}?lang={lang}").status_code, 200, path)
