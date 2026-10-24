"""Livelihoods: chosen before setting up, menus that show only what fits, My farm, reminders, money and selling."""
from datetime import timedelta
from decimal import Decimal as D

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User, UserStatus
from farming import farm, livelihoods as lh
from farming.models import FarmEntry, FarmUnit
from market.models import Listing
from notify.models import InboxItem
from profiles.models import OrgMembership, Organisation
from web.tests.test_market_web import NOTIFY_MEM, make_farmer
from web.tests.test_web import WebCase, web_login

TODAY = timezone.localdate()


def silk_farmer(phone="9000000401", segs=("sericulture",)):
    u = make_farmer(phone)
    fp = u.farmer_profile
    fp.segments = list(segs)
    if "crops" not in segs:
        fp.crops = []
    fp.save()
    return u


class StartTests(WebCase):
    def test_a_new_farmer_chooses_livelihoods_before_the_profile(self):
        web_login(self.client)
        self.assertRedirects(self.client.get("/farmer/"), "/start/", fetch_redirect_response=False)
        page = self.client.get("/start/?lang=en").content.decode()
        for code in lh.CODES:
            self.assertIn(f'value="{code}"', page)
        self.assertRedirects(self.client.post("/start/", {"segments": ["sericulture"]}), "/farmer/profile/", fetch_redirect_response=False)
        form_page = self.client.get("/farmer/profile/?lang=en").content.decode()
        self.assertNotIn('name="crops"', form_page)  # no crop questions for a silk farmer
        self.client.post("/farmer/profile/", {"name": "Sunita", "village": "Gurh", "state": "Madhya Pradesh", "district": "Rewa"})
        fp = User.objects.get(phone="9876543210").farmer_profile
        self.assertEqual((fp.segments, fp.level), (["sericulture"], 1))
        self.assertEqual(self.client.get("/farmer/").status_code, 200)

    def test_nothing_chosen_is_refused(self):
        web_login(self.client)
        self.client.post("/start/", {})
        self.assertEqual(User.objects.get(phone="9876543210").farmer_profile.segments, [])


class MenuTests(TestCase):
    def page(self, user):
        c = Client()
        c.force_login(user)
        return c.get("/farm/?lang=en" if lh.of(user) != ["crops"] else "/farmer/?lang=en").content.decode()

    def test_each_farmer_sees_only_their_tools(self):
        silk = self.page(silk_farmer())
        self.assertIn('href="/farm/"', silk)
        self.assertIn("🐛", silk)  # the menu shows their own livelihood
        for crop_tool in ('href="/farmer/book/"', 'href="/rates/"', 'href="/storage/"', 'href="/insurance/"'):
            self.assertNotIn(crop_tool, silk)
        crop = self.page(make_farmer("9000000402"))
        self.assertIn('href="/farmer/book/"', crop)
        self.assertNotIn('href="/farm/"', crop)
        both = self.page(silk_farmer("9000000403", ("crops", "dairy")))
        self.assertIn('href="/farmer/book/"', both)
        self.assertIn('href="/farm/"', both)


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class FarmTests(TestCase):
    def setUp(self):
        self.u = silk_farmer("9000000404", ("crops", "poultry", "dairy"))
        self.c = Client()
        self.c.force_login(self.u)

    def add(self, livelihood="poultry", kind="broiler", days_ago=5, count=500):
        self.c.post("/farm/new/", {"action": "save", "livelihood": livelihood, "kind": kind, "name": "Batch March", "count": count,
                                   "started_on": (TODAY - timedelta(days=days_ago)).isoformat()})
        return FarmUnit.objects.latest("pk")

    def test_unit_reminders_come_from_the_schedule_and_go_once_done(self):
        un = self.add()
        due = farm.due_tasks(un)
        self.assertTrue(any("Ranikhet" in t["text"] and t["date"] == TODAY for t in due))
        self.assertEqual(farm.send_reminders(), 1)  # the ND vaccine falls today (the weekly shed check fell 5 days ago and falls again in 2)
        self.assertEqual(farm.send_reminders(), 0)  # never twice
        self.assertTrue(InboxItem.objects.filter(user=self.u, kind="farm").exists())
        ref = next(t["ref"] for t in due if "Ranikhet" in t["text"])
        self.c.post(f"/farm/{un.pk}/", {"action": "done", "ref": ref})
        self.assertFalse(any(t["ref"] == ref for t in farm.due_tasks(un)))

    def test_entries_feed_the_profit_and_loss_and_the_whole_farm(self):
        from farmerbook.statement import build
        from farmerbook.views import ledger_for
        un = self.add("dairy", "cow", 30, 4)
        for kind, qty, amt in (("produce", "40", ""), ("sale", "40", "2400"), ("feed", "", "900"), ("loss", "1", ""), ("added", "2", "")):
            self.c.post(f"/farm/{un.pk}/", {"action": "entry", "kind": kind, "quantity": qty, "amount": amt})
        self.assertEqual(farm.summary(un)["head"], 5)  # 4 + 2 born - 1 lost
        self.assertEqual(ledger_for(self.u)["totals"]["profit"], "1500.00")
        st = build(self.u, TODAY - timedelta(days=30), TODAY)
        self.assertTrue(any(r["crop"] == "dairy" and r["net"] == "1500.00" for r in st["crops"]))
        self.assertEqual([r["code"] for r in farm.whole_farm(self.u)], ["dairy"])
        self.assertContains(self.c.get("/farm/?lang=en"), "Whole farm, last 12 months")

    def test_sell_milk_by_the_litre_from_the_dairy_unit(self):
        un = self.add("dairy", "cow", 30, 4)
        r = self.c.post(f"/farmer/sell/new/?farm_unit={un.pk}&product=milk", {"unit": "litre", "quantity": "50", "price": "48", "grade": "ungraded",
                                                                         "state": "Madhya Pradesh", "district": "Rewa", "village": "Gurh",
                                                                         "available_from": TODAY.isoformat()})
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        li = Listing.objects.get()
        self.assertRedirects(r, f"/farmer/sell/{li.pk}/", fetch_redirect_response=False)
        self.assertEqual((li.crop, li.form, li.unit, li.source_unit), ("milk", "live", "litre", un))
        self.c.get(f"/farmer/sell/new/?farm_unit={un.pk}&product=honey")  # honey is not from a dairy unit
        self.assertEqual(Listing.objects.count(), 1)
        self.assertContains(Client().get("/produce/milk/?lang=en"), "Buy Milk directly")

    def test_nobody_else_can_open_or_sell_from_a_unit(self):
        un = self.add()
        other = Client()
        other.force_login(silk_farmer("9000000405", ("poultry",)))
        self.assertEqual(other.get(f"/farm/{un.pk}/").status_code, 404)
        self.assertRedirects(other.get(f"/farmer/sell/new/?farm_unit={un.pk}&product=eggs"), "/farm/", fetch_redirect_response=False)


class FpoTests(TestCase):
    def test_fpo_chooses_its_livelihoods_and_sees_members_farms(self):
        org = Organisation.objects.create(name="Gurh Dairy FPO", code="gurhdairy", district="Rewa", verified=True)
        agent = User.objects.create_user("9833333334", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        ac = Client()
        ac.force_login(agent)
        self.assertContains(ac.get("/fpo/?lang=en"), "What do your members do?")  # existing FPOs are asked, not blocked
        ac.post("/start/", {"segments": ["dairy"]})
        org.refresh_from_db()
        self.assertEqual(org.segments, ["dairy"])
        member = silk_farmer("9000000406", ("dairy",))
        fp = member.farmer_profile
        fp.organisation, fp.org_status = org, "confirmed"
        fp.save()
        un = FarmUnit.objects.create(owner=member, livelihood="dairy", kind="cow", name="Home shed", count=6, started_on=TODAY - timedelta(days=10))
        FarmEntry.objects.create(unit=un, owner=member, kind="produce", date=TODAY, quantity=D("30"))
        page = ac.get("/fpo/farm/?lang=en").content.decode()
        self.assertIn("Dairy", page)
        self.assertIn("30", page)
        self.assertNotIn('href="/fpo/pools/"', ac.get("/fpo/?lang=en").content.decode())  # a dairy FPO has no crop group selling
        self.assertEqual(len(ac.get("/fpo/farmers/?seg=dairy").context["rows"]), 1)
        self.assertEqual(len(ac.get("/fpo/farmers/?seg=fisheries").context["rows"]), 0)
