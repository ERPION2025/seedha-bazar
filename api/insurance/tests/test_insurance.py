from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from accounts.errors import ApiError
from accounts.models import Role, User, UserStatus
from farmerbook.models import CropCycle, Plot
from insurance import connectors, rules, services
from insurance.models import Application, Plan
from profiles.models import Organisation, OrgMembership
from rates.models import MarketRate
from web.tests.test_market_web import TODAY, make_farmer

D = Decimal


class RuleTests(TestCase):
    def setUp(self):
        call_command("seed_insurance", stdout=StringIO())

    def test_crop_groups_and_seasons(self):
        self.assertEqual((rules.group_of("wheat"), rules.group_of("tomato"), rules.group_of("cotton")), ("food", "commercial", "commercial"))
        self.assertEqual((rules.season_for("wheat", "rabi"), rules.season_for("tomato", "kharif")), ("rabi", "annual"))

    def test_national_shares_apply_when_the_state_has_not_been_loaded(self):
        plans = services.plans_for("wheat", "Madhya Pradesh", "Rewa", "rabi")
        self.assertEqual({(p.scheme, p.farmer_share_pct) for p in plans}, {("pmfby", D("1.5")), ("rwbcis", D("1.5"))})
        self.assertEqual({p.farmer_share_pct for p in services.plans_for("onion", "Madhya Pradesh", "Rewa", "rabi")}, {D("5")})

    def test_a_state_notification_replaces_the_national_rule_for_its_districts(self):
        Plan.objects.create(scheme="pmfby", state="Madhya Pradesh", season="kharif", crop="soybean", districts=["Rewa"], farmer_share_pct=2,
                            sum_insured_per_ha=50000, cutoff_date=TODAY + timedelta(days=10), insurer="Example General Insurance", notified=True)
        plans = services.plans_for("soybean", "Madhya Pradesh", "Rewa", "kharif")
        self.assertEqual(len(plans), 1)
        q = services.quote(plans[0], D("2"))
        self.assertEqual((q["sum_insured"], q["premium"], q["basis"], q["times"]), (D("100000"), D("2000"), "notified", D("50")))
        self.assertEqual(services.days_left(plans[0]), 10)
        self.assertNotEqual(len(services.plans_for("soybean", "Madhya Pradesh", "Satna", "kharif")), 1)  # another district gets the national rule

    def test_a_csv_notification_loads(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as fh:
            fh.write("scheme,state,season,crop,districts,farmer_share_pct,sum_insured_per_ha,cutoff_date,insurer,source\n")
            fh.write("pmfby,Madhya Pradesh,kharif,Soyabean,Rewa|Satna,2,48000,2026-07-31,Example Insurance,MP notification 2026\n")
        call_command("load_insurance_plans", fh.name, stdout=StringIO())
        p = Plan.objects.get(state="Madhya Pradesh")
        self.assertEqual((p.crop, p.districts, p.sum_insured_per_ha, p.notified), ("soybean", ["Rewa", "Satna"], D("48000"), True))

    def test_value_estimate_uses_todays_rate(self):
        MarketRate.objects.create(source="agmarknet", date=TODAY, state="Madhya Pradesh", district="Rewa", market="Rewa", commodity="Wheat", variety="x", crop="wheat",
                                  min_price=2300, max_price=2500, modal_price=2400)
        v = services.crop_value("wheat", "Madhya Pradesh", "Rewa", D("1"), D("40"))
        self.assertEqual(v["value"], D("96000"))

    def test_without_a_partner_agreement_the_manual_connector_is_used(self):
        self.assertEqual(connectors.get().name, "manual")
        with self.settings(INSURANCE_CONNECTOR="pmfby_partner"):
            self.assertEqual(connectors.get().name, "manual")  # no credentials, so it falls back


class JourneyTests(TestCase):
    def setUp(self):
        call_command("seed_insurance", stdout=StringIO())
        self.farmer = make_farmer()
        plot = Plot.objects.create(owner=self.farmer, name="Home", area_acres=D("2.5"))
        self.cycle = CropCycle.objects.create(owner=self.farmer, plot=plot, crop="wheat", season="rabi")
        self.c = Client()
        self.c.force_login(self.farmer)

    def compare_query(self, **over):
        q = {"crop": "wheat", "season": "rabi", "area": "2.5", "area_unit": "acre", "value": "100000", "state": "Madhya Pradesh", "district": "Rewa", "cycle": str(self.cycle.client_id)}
        q.update(over)
        from urllib.parse import urlencode
        return urlencode(q)

    def test_compare_prefills_from_the_book_and_works_out_the_cost(self):
        r = self.c.get(f"/insurance/compare/?cycle={self.cycle.client_id}&lang=en")
        self.assertEqual(r.context["form"].initial["crop"], "wheat")
        r = self.c.get(f"/insurance/compare/?{self.compare_query()}&lang=en")
        opts = r.context["options"]
        self.assertEqual((opts[0]["plan"].scheme, opts[0]["premium"], opts[0]["sum_insured"]), ("pmfby", D("1500"), D("100000")))
        self.assertContains(r, "Opt in with this plan")

    def test_full_journey_opt_in_papers_submit_enrol_and_report_loss(self):
        plan = Plan.objects.get(scheme="pmfby", season="rabi")
        r = self.c.post("/insurance/apply/", {"plan": plan.pk, "query": self.compare_query(), "channel": "csc"})
        app = Application.objects.get()
        self.assertRedirects(r, f"/insurance/{app.pk}/", fetch_redirect_response=False)
        self.assertEqual((app.crop_cycle, app.area_ha, app.farmer_premium, app.status, app.channel), (self.cycle, D("1.012"), D("1500"), "draft", "csc"))
        self.c.post(f"/insurance/{app.pk}/papers/", {"ready": ["aadhaar", "land", "bank", "sowing"]})
        app.refresh_from_db()
        self.assertEqual(app.status, "ready")
        self.c.post(f"/insurance/{app.pk}/loss/", {"loss_date": TODAY.isoformat(), "cause": "hail"})
        app.refresh_from_db()
        self.assertEqual(app.status, "ready")  # a loss cannot be reported before submitting
        self.c.post(f"/insurance/{app.pk}/submitted/", {"application_no": "PMFBY-123"})
        self.c.post(f"/insurance/{app.pk}/enrolled/", {"policy_no": "POL-9", "insurer": "Example Insurance"})
        self.c.post(f"/insurance/{app.pk}/loss/", {"loss_date": TODAY.isoformat(), "cause": "hail", "note": "Hail on Tuesday night"})
        app.refresh_from_db()
        self.assertEqual((app.status, app.application_no, app.policy_no, app.loss_cause), ("loss", "PMFBY-123", "POL-9", "hail"))
        page = self.c.get(f"/insurance/{app.pk}/?lang=en").content.decode()
        self.assertIn("hours left to report", page)
        self.assertEqual(self.c.get(f"/insurance/{app.pk}/print/?lang=hi").status_code, 200)

    def test_the_same_crop_cannot_be_insured_twice_and_closed_plans_refuse(self):
        plan = Plan.objects.get(scheme="pmfby", season="rabi")
        self.c.post("/insurance/apply/", {"plan": plan.pk, "query": self.compare_query()})
        self.c.post("/insurance/apply/", {"plan": plan.pk, "query": self.compare_query()})
        self.assertEqual(Application.objects.count(), 1)
        closed = Plan.objects.create(scheme="pmfby", state="Madhya Pradesh", season="rabi", crop="gram", farmer_share_pct=D("1.5"), cutoff_date=TODAY - timedelta(days=1), notified=True)
        with self.assertRaises(ApiError):
            services.create_application(self.farmer, {"plan": closed, "crop": "gram", "area_ha": D("1"), "sum_insured": D("50000"), "state": "x", "district": "y", "year": 2026})

    def test_others_cannot_see_an_application_but_its_fpo_can(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        fp = self.farmer.farmer_profile
        fp.organisation, fp.org_status = org, "confirmed"
        fp.save()
        agent = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        ac = Client()
        ac.force_login(agent)
        self.assertContains(ac.get("/fpo/insurance/?lang=en"), "Ramesh Kushwaha")
        plan = Plan.objects.get(scheme="pmfby", season="rabi")
        ac.post("/insurance/apply/", {"plan": plan.pk, "for": self.farmer.pk, "query": self.compare_query(cycle="", **{"for": self.farmer.pk})})
        app = Application.objects.get()
        self.assertEqual((app.farmer, app.helped_by, app.organisation, app.channel), (self.farmer, agent, org, "fpo"))
        self.assertEqual(ac.get(f"/insurance/{app.pk}/").status_code, 200)
        stranger = Client()
        stranger.force_login(make_farmer("9000000077"))
        self.assertEqual(stranger.get(f"/insurance/{app.pk}/").status_code, 404)
        self.assertEqual(stranger.post(f"/insurance/{app.pk}/close/").status_code, 404)

    def test_pages_render_in_every_language(self):
        for who in (self.farmer,):  # nothing opens before sign-in
            c = Client()
            if who:
                c.force_login(who)
            for lang in ("hi", "mr", "en"):
                for path in ("/insurance/", "/insurance/norms/", "/insurance/compare/", f"/insurance/compare/?{self.compare_query()}"):
                    self.assertEqual(c.get(f"{path}{'&' if '?' in path else '?'}lang={lang}").status_code, 200, (path, lang))
