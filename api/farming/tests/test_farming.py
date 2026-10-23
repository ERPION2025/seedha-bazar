from decimal import Decimal as D

from django.test import Client, TestCase, override_settings

from engagement import scores
from extension.tests.test_extension import make_centre
from farming import services
from farming.models import CropGroup
from notify.models import Message
from profiles.models import OrgMembership, Organisation
from accounts.models import Role, User, UserStatus
from web.tests.test_market_web import NOTIFY_MEM, make_buyer, make_farmer


@override_settings(NOTIFY_BACKENDS=NOTIFY_MEM)
class GroupTests(TestCase):
    def setUp(self):
        self.lead = make_farmer()
        self.other = make_farmer("9000000201")
        for u in (self.lead, self.other):
            fp = u.farmer_profile
            fp.crops = ["wheat"]
            fp.save()
        self.fc = Client()
        self.fc.force_login(self.lead)

    def test_start_join_and_neighbours_are_invited(self):
        r = self.fc.post("/farmer/groups/", {"crop": "wheat", "season": "rabi", "year": "2026", "village": "Naigarhi", "seed_variety": "HI-1544",
                                             "practices": ["same_seed", "sell_together"], "acres": "3"})
        g = CropGroup.objects.get()
        self.assertRedirects(r, f"/farmer/groups/{g.pk}/", fetch_redirect_response=False)
        self.assertTrue(Message.objects.filter(phone=self.other.phone, template="group_invite").exists())
        oc = Client()
        oc.force_login(self.other)
        self.assertContains(oc.get("/farmer/groups/?lang=en"), "Naigarhi")
        oc.post(f"/farmer/groups/{g.pk}/", {"action": "join", "acres": "2.5"})
        s = services.stats(g)
        self.assertEqual((s["members"], s["acres"]), (2, D("5.5")))
        self.assertEqual(s["parts"][-1]["got"], 4)  # two practices agreed

    def test_a_farmer_from_another_district_cannot_join(self):
        g = services.create(self.lead, crop="wheat", season="rabi", year=2026, district="Rewa", state="Madhya Pradesh", invite=False)
        far = make_farmer("9000000202")
        fp = far.farmer_profile
        fp.district = "Satna"
        fp.save()
        with self.assertRaises(Exception):
            services.join(g, far, 2)

    def test_group_counts_in_performance_and_shows_to_buyers(self):
        before = scores.performance(self.lead)
        g = services.create(self.lead, crop="wheat", season="rabi", year=2026, district="Rewa", state="Madhya Pradesh", invite=False, lead_acres=3)
        g.centre = make_centre()
        g.save()
        part = next(p for p in scores.performance(self.lead)["parts"] if p["label"] == "Group farming")
        self.assertGreaterEqual(part["got"], 5)
        self.assertGreater(scores.performance(self.lead)["score"], before["score"])
        fp = self.lead.farmer_profile
        fp.discoverable, fp.level = True, 2
        fp.save()
        bc = Client()
        bc.force_login(make_buyer())
        self.assertContains(bc.get(f"/producers/farmer/{self.lead.pk}/?lang=en"), "Farms in a group")

    def test_fpo_runs_groups_for_its_members(self):
        org = Organisation.objects.create(name="Naigarhi FPO", code="naigarhi", district="Rewa", verified=True)
        agent = User.objects.create_user("9833333333", role=Role.AGENT, status=UserStatus.ACTIVE)
        OrgMembership.objects.create(user=agent, organisation=org)
        ac = Client()
        ac.force_login(agent)
        ac.post("/fpo/groups/", {"crop": "wheat", "season": "rabi", "year": "2026", "village": "Naigarhi", "practices": ["sell_together"]})
        g = CropGroup.objects.get()
        self.assertEqual((g.organisation, g.lead), (org, None))
        services.join(g, self.lead, 3)
        self.assertContains(ac.get("/fpo/?lang=en"), "1 crop groups")
        self.assertEqual(ac.get(f"/fpo/groups/{g.pk}/?lang=en").status_code, 200)
