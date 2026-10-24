from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.utils import timezone

from accounts.models import Role, User, UserStatus
from farmerbook import statement
from farmerbook.models import Expense, Sale, Statement
from profiles.models import Organisation, OrgMembership
from web.tests.test_market_web import make_farmer, stocked_cycle

D = Decimal


class StatementTests(TestCase):
    def setUp(self):
        self.f = make_farmer()
        self.cycle = stocked_cycle(self.f, 20, crop="wheat")
        today = timezone.localdate()
        Expense.objects.create(owner=self.f, crop_cycle=self.cycle, category="seed", amount=3000, date=today)
        Sale.objects.create(owner=self.f, crop_cycle=self.cycle, date=today, quantity=10, unit="quintal", quantity_kg=1000, rate=2400, amount=24000, channel="mandi")
        self.c = Client()
        self.c.force_login(self.f)

    def test_statement_adds_up_freezes_and_can_be_verified_publicly(self):
        r = self.c.post("/statement/new/", {"from": (timezone.localdate() - timedelta(days=30)).isoformat(), "to": timezone.localdate().isoformat()})
        s = Statement.objects.get()
        self.assertRedirects(r, f"/statement/{s.code}/", fetch_redirect_response=False)
        self.assertEqual(s.data["totals"], {"income": "24000.00", "expenses": "3000.00", "net": "21000.00", "general_expenses": "0.00", "per_acre_net": "7000.00"})
        page = self.c.get(f"/statement/{s.code}/?lang=en").content.decode()
        self.assertIn(self.f.phone, page)
        self.assertIn(s.digest, page)
        anon = Client()
        self.assertEqual(anon.get(f"/statement/{s.code}/").status_code, 302)  # the full copy is private: sign in first
        v = anon.get(f"/verify/{s.code}/?lang=en").content.decode()
        self.assertIn("has not been changed", v)
        self.assertNotIn(self.f.phone, v)
        Statement.objects.filter(pk=s.pk).update(data={**s.data, "totals": {**s.data["totals"], "net": "99999.00"}})
        self.assertIn("do not match", anon.get(f"/verify/{s.code}/?lang=en").content.decode())
        self.assertIn("No statement", anon.get("/verify/nothere/?lang=en").content.decode())

    def test_an_fpo_agent_can_make_one_for_a_member_only(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        agent = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        ac = Client()
        ac.force_login(agent)
        self.assertEqual(ac.get(f"/statement/?for={self.f.pk}").status_code, 302)  # not a member yet
        fp = self.f.farmer_profile
        fp.organisation, fp.org_status = org, "confirmed"
        fp.save()
        self.assertEqual(ac.get(f"/statement/?for={self.f.pk}&lang=en").status_code, 200)
        ac.post("/statement/new/", {"for": self.f.pk})
        s = Statement.objects.get()
        self.assertEqual((s.owner, s.made_by, s.data["farmer"]["fpo"]), (self.f, agent, "Naigarhi FPO"))
        self.assertEqual(ac.get(f"/statement/{s.code}/").status_code, 200)

    def test_pages_render(self):
        for lang in ("hi", "mr", "en"):
            self.assertEqual(self.c.get(f"/statement/?lang={lang}").status_code, 200)
