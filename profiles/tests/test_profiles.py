from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.messaging import MemoryBackend
from accounts.models import AuditEvent, OtpChallenge, Role, User, UserStatus
from accounts.tests.helpers import DEVICE, authed, last_code, login
from profiles.models import FarmerProfile, OrgLinkRequest, Organisation, OrgMembership, OrgStatus

FULL = {"name": "Ramesh Kushwaha", "village": "Naigarhi", "district": "Rewa", "land_acres": "3.5", "crops": ["wheat", "kodo"]}


def make_agent(phone="9000000001", org_code="naigarhi"):
    org, _ = Organisation.objects.get_or_create(code=org_code, defaults={"name": "Naigarhi FPO", "district": "Rewa", "verified": True})
    agent = User.objects.create_user(phone=phone, role=Role.AGENT, status=UserStatus.ACTIVE)
    OrgMembership.objects.create(user=agent, organisation=org)
    return agent, org


def sign_in_as(user, device="device-agnt-0001"):
    """Create an authenticated client for a user created directly (agents are staff-provisioned)."""
    from accounts import tokens
    from accounts.models import Device
    d = Device.objects.create(user=user, device_id=device)
    return authed(tokens.issue(d)["access"])


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class FarmerProfileTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.session = login(APIClient()).data
        self.a = authed(self.session["access"])

    def test_empty_profile_is_level_zero(self):
        r = self.a.get("/api/farmers/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["level"], 0)

    def test_complete_basics_gives_level_one(self):
        r = self.a.patch("/api/farmers/me", FULL, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["level"], 1)

    def test_partial_basics_stays_level_zero(self):
        r = self.a.patch("/api/farmers/me", {"name": "Ramesh", "village": "Naigarhi"}, format="json")
        self.assertEqual(r.data["level"], 0)

    def test_client_cannot_set_level_or_org_status(self):
        r = self.a.patch("/api/farmers/me", {**FULL, "level": 3, "org_status": "confirmed"}, format="json")
        self.assertEqual(r.data["level"], 1)
        self.assertEqual(r.data["org_status"], "none")

    def test_bad_land_size_rejected(self):
        self.assertEqual(self.a.patch("/api/farmers/me", {"land_acres": "-2"}, format="json").status_code, 400)
        self.assertEqual(self.a.patch("/api/farmers/me", {"land_acres": "9999999"}, format="json").status_code, 400)

    def test_too_many_crops_rejected(self):
        self.assertEqual(self.a.patch("/api/farmers/me", {"crops": [f"c{i}" for i in range(25)]}, format="json").status_code, 400)

    def test_buyer_cannot_use_farmer_endpoint(self):
        b = authed(login(APIClient(), phone="9333333333", device="device-buyr-0001", role="buyer").data["access"])
        self.assertEqual(b.get("/api/farmers/me").status_code, 403)
        self.assertEqual(self.a.get("/api/buyers/me").status_code, 403)

    def test_language_change(self):
        r = self.a.patch("/api/me", {"language": "mr"}, format="json")
        self.assertEqual(r.data["language"], "mr")
        self.assertEqual(self.a.patch("/api/me", {"language": "xx"}, format="json").status_code, 400)


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class BuyerProfileTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.a = authed(login(APIClient(), phone="9333333333", role="buyer").data["access"])

    def test_levels(self):
        self.assertEqual(self.a.get("/api/buyers/me").data["level"], 0)
        r = self.a.patch("/api/buyers/me", {"business_name": "Hotel Rewa Palace", "business_type": "hotel_restaurant", "city": "Bhopal"}, format="json")
        self.assertEqual(r.data["level"], 1)

    def test_gstin_and_fssai_validation(self):
        self.assertEqual(self.a.patch("/api/buyers/me", {"gstin": "123"}, format="json").status_code, 400)
        self.assertEqual(self.a.patch("/api/buyers/me", {"fssai": "12"}, format="json").status_code, 400)
        self.assertEqual(self.a.patch("/api/buyers/me", {"gstin": "23abcde1234f1z5"}, format="json").data["gstin"], "23ABCDE1234F1Z5")


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class AssistedOnboardingTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.agent, self.org = make_agent()
        self.ac = sign_in_as(self.agent)

    def add_farmer(self, phone="9444444444", **extra):
        return self.ac.post("/api/agent/farmers", {"phone": phone, **FULL, **extra}, format="json")

    def test_full_assisted_flow_farmer_owns_account(self):
        r = self.add_farmer()
        self.assertEqual(r.status_code, 201, r.content)
        farmer = User.objects.get(phone="9444444444")
        self.assertEqual(farmer.status, UserStatus.PENDING)
        self.assertEqual(farmer.created_by, self.agent)
        fp = farmer.farmer_profile
        self.assertEqual((fp.org_status, fp.assisted_by), (OrgStatus.PENDING, self.agent))
        self.assertEqual(fp.level, 1)  # complete but not yet confirmed by the owner
        # a code went to the farmer's own phone, and the agent never receives tokens for this account
        code = last_code("9444444444")
        self.assertEqual(MemoryBackend.outbox[-1]["phone"], "9444444444")
        r2 = APIClient().post("/api/auth/otp/verify", {"phone": "9444444444", "code": code, "device_id": "device-farm-0001", "consent": True}, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(r2.data["is_new_user"])
        farmer.refresh_from_db()
        self.assertEqual(farmer.status, UserStatus.ACTIVE)
        self.assertIsNotNone(farmer.consented_at)
        fp.refresh_from_db()
        self.assertEqual(fp.org_status, OrgStatus.CONFIRMED)
        self.assertEqual(fp.level, 2)
        self.assertEqual(r2.data["user"]["level"], 2)
        self.assertTrue(AuditEvent.objects.filter(action="owner_confirmed").exists())

    def test_pending_account_cannot_use_farmer_apis_until_confirmed(self):
        self.add_farmer()
        from accounts import tokens
        from accounts.models import Device
        farmer = User.objects.get(phone="9444444444")
        d = Device.objects.create(user=farmer, device_id="device-hack-0001")
        c = authed(tokens.issue(d)["access"])
        self.assertEqual(c.get("/api/farmers/me").status_code, 403)

    def test_existing_number_is_not_overwritten(self):
        login(APIClient(), phone="9555555555", device="device-owner-001")
        r = self.add_farmer(phone="9555555555")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["error"]["code"], "already_registered")

    def test_family_number_flag_saved(self):
        self.add_farmer(contact_is_family=True, family_contact_name="Son")
        fp = User.objects.get(phone="9444444444").farmer_profile
        self.assertTrue(fp.contact_is_family)
        self.assertEqual(fp.family_contact_name, "Son")

    def test_farmer_role_cannot_use_agent_endpoints(self):
        f = authed(login(APIClient(), phone="9666666666", device="device-farm-0002").data["access"])
        self.assertEqual(f.post("/api/agent/farmers", {"phone": "9777777777", **FULL}, format="json").status_code, 403)
        self.assertEqual(f.get("/api/agent/farmers").status_code, 403)

    def test_agent_needs_org_membership_choice(self):
        other = Organisation.objects.create(name="Gangeo FPO", code="gangeo", verified=True)
        OrgMembership.objects.create(user=self.agent, organisation=other)
        r = self.add_farmer()
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["code"], "org_required")
        r = self.add_farmer(org_code="gangeo")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.get(phone="9444444444").farmer_profile.organisation, other)

    def test_agent_cannot_add_to_org_they_do_not_belong_to(self):
        Organisation.objects.create(name="Other FPO", code="other", verified=True)
        self.assertEqual(self.add_farmer(org_code="other").status_code, 400)

    def test_agent_lists_only_own_org_farmers_and_can_resend(self):
        self.add_farmer()
        other_agent, other_org = make_agent(phone="9000000002", org_code="gangeo")
        oc = sign_in_as(other_agent, "device-agnt-0002")
        self.assertEqual(len(self.ac.get("/api/agent/farmers").data["farmers"]), 1)
        self.assertEqual(len(oc.get("/api/agent/farmers").data["farmers"]), 0)
        farmer = User.objects.get(phone="9444444444")
        OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self.ac.post(f"/api/agent/farmers/{farmer.pk}/resend", {}, format="json").status_code, 200)
        # another agent cannot resend for a farmer they did not add
        OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(oc.post(f"/api/agent/farmers/{farmer.pk}/resend", {}, format="json").status_code, 404)

    def test_daily_limit(self):
        from profiles import services
        with override_settings():
            services.MAX_NEW_FARMERS_PER_AGENT_PER_DAY = 1
            try:
                self.assertEqual(self.add_farmer().status_code, 201)
                OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
                self.assertEqual(self.add_farmer(phone="9888888888").status_code, 429)
            finally:
                services.MAX_NEW_FARMERS_PER_AGENT_PER_DAY = 100


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class JoinOrgTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.agent, self.org = make_agent()
        self.ac = sign_in_as(self.agent)
        self.farmer = authed(login(APIClient(), phone="9666666666", device="device-farm-0002").data["access"])
        self.farmer.patch("/api/farmers/me", FULL, format="json")

    def test_join_request_and_approval_raises_level(self):
        r = self.farmer.post("/api/farmers/me/join-org", {"org_code": "naigarhi"}, format="json")
        self.assertEqual(r.status_code, 201)
        pending = self.ac.get("/api/agent/join-requests").data["requests"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(self.ac.post(f"/api/agent/join-requests/{pending[0]['id']}/approve").status_code, 200)
        me = self.farmer.get("/api/farmers/me").data
        self.assertEqual((me["org_status"], me["level"]), ("confirmed", 2))
        self.assertEqual(me["organisation"]["name"], "Naigarhi FPO")

    def test_duplicate_request_is_not_duplicated(self):
        self.farmer.post("/api/farmers/me/join-org", {"org_code": "naigarhi"}, format="json")
        self.farmer.post("/api/farmers/me/join-org", {"org_code": "naigarhi"}, format="json")
        self.assertEqual(OrgLinkRequest.objects.count(), 1)

    def test_reject_leaves_farmer_unlinked(self):
        self.farmer.post("/api/farmers/me/join-org", {"org_code": "naigarhi"}, format="json")
        link = OrgLinkRequest.objects.get()
        self.assertEqual(self.ac.post(f"/api/agent/join-requests/{link.pk}/reject").status_code, 200)
        self.assertEqual(self.farmer.get("/api/farmers/me").data["level"], 1)
        self.assertEqual(self.ac.post(f"/api/agent/join-requests/{link.pk}/approve").status_code, 409)

    def test_wrong_agent_cannot_decide(self):
        self.farmer.post("/api/farmers/me/join-org", {"org_code": "naigarhi"}, format="json")
        other, _ = make_agent(phone="9000000002", org_code="gangeo")
        oc = sign_in_as(other, "device-agnt-0002")
        link = OrgLinkRequest.objects.get()
        self.assertEqual(oc.post(f"/api/agent/join-requests/{link.pk}/approve").status_code, 404)

    def test_unknown_code(self):
        r = self.farmer.post("/api/farmers/me/join-org", {"org_code": "nope"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_org_search_only_verified(self):
        Organisation.objects.create(name="Unverified FPO", code="unv", verified=False)
        names = [o["name"] for o in self.farmer.get("/api/orgs").data["organisations"]]
        self.assertIn("Naigarhi FPO", names)
        self.assertNotIn("Unverified FPO", names)
        self.assertNotIn("code", self.farmer.get("/api/orgs").data["organisations"][0])


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class DeleteAccountTests(TestCase):
    def test_delete_anonymises_and_ends_sessions(self):
        MemoryBackend.outbox.clear()
        s = login(APIClient()).data
        a = authed(s["access"])
        a.patch("/api/farmers/me", FULL, format="json")
        self.assertEqual(a.post("/api/me/delete", {}, format="json").status_code, 400)
        self.assertEqual(a.post("/api/me/delete", {"confirm": "DELETE"}, format="json").status_code, 204)
        self.assertEqual(a.get("/api/me").status_code, 401)
        u = User.objects.get()
        self.assertEqual(u.status, UserStatus.DELETED)
        self.assertNotEqual(u.phone, "9876543210")
        fp = FarmerProfile.objects.get()
        self.assertEqual((fp.name, fp.village, fp.crops), ("", "", []))
        self.assertTrue(AuditEvent.objects.filter(action="account_deleted").exists())
        # the number can register again as a fresh account
        OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
        r = login(APIClient())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.count(), 2)
