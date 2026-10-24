from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.messaging import MemoryBackend
from accounts import otp
from accounts.models import AuditEvent, Device, OtpChallenge, Role, User
from accounts.phone import InvalidPhone, normalise_phone

from .helpers import DEVICE, authed, last_code, login


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class PhoneTests(TestCase):
    def test_normalisation(self):
        for raw in ["9876543210", "+91 98765 43210", "09876543210", "919876543210", "९८७६५४३२१०", "98765-43210"]:
            self.assertEqual(normalise_phone(raw), "9876543210", raw)

    def test_rejects_bad_numbers(self):
        for raw in ["12345", "5876543210", "98765432101", "abcdefghij", ""]:
            with self.assertRaises(InvalidPhone):
                normalise_phone(raw)


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class OtpFlowTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.c = APIClient()

    def test_new_user_login_creates_account_and_tokens(self):
        r = login(self.c)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data["is_new_user"])
        self.assertEqual(r.data["user"]["role"], "farmer")
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        user = User.objects.get(phone="9876543210")
        self.assertEqual(user.status, "active")
        self.assertIsNotNone(user.consented_at)
        self.assertTrue(hasattr(user, "farmer_profile"))

    def test_existing_user_gets_200(self):
        login(self.c)
        MemoryBackend.outbox.clear()
        OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
        r = login(self.c)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["is_new_user"])

    def test_request_reply_does_not_reveal_registration(self):
        a = self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        User.objects.create_user(phone="9123456780", status="active")
        b = self.c.post("/api/auth/otp/request", {"phone": "9123456780"}, format="json")
        self.assertEqual(a.status_code, b.status_code)
        self.assertEqual(set(a.data), set(b.data))

    def test_devanagari_code_and_phone_accepted(self):
        self.c.post("/api/auth/otp/request", {"phone": "९८७६५४३२१०"}, format="json")
        code = last_code("9876543210").translate(str.maketrans("0123456789", "०१२३४५६७८९"))
        r = self.c.post("/api/auth/otp/verify", {"phone": "९८७६५४३२१०", "code": code, "device_id": DEVICE, "consent": True}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_wrong_code_then_lockout(self):
        self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        good = last_code("9876543210")
        bad = "000000" if good != "000000" else "111111"
        for _ in range(5):
            r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": bad, "device_id": DEVICE, "consent": True}, format="json")
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.data["error"]["code"], "invalid_or_expired_code")
        # even the right code is now dead: a new one must be requested
        r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": good, "device_id": DEVICE, "consent": True}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_code_is_single_use(self):
        r = login(self.c)
        code = last_code("9876543210")
        again = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": code, "device_id": "device-bbbb-2222", "consent": True}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_expired_code(self):
        self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        OtpChallenge.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": last_code("9876543210"), "device_id": DEVICE, "consent": True}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_consent_required(self):
        self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": last_code("9876543210"), "device_id": DEVICE, "consent": False}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(phone="9876543210").exists())

    def test_cannot_self_assign_privileged_role(self):
        self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": last_code("9876543210"), "device_id": DEVICE, "consent": True, "role": "admin"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_resend_cooldown_and_hourly_limit(self):
        r1 = self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        self.assertEqual(r1.status_code, 200)
        r2 = self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        self.assertEqual(r2.status_code, 429)
        self.assertEqual(r2.data["error"]["code"], "otp_cooldown")
        self.assertIn("Retry-After", r2)
        for _ in range(4):
            OtpChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=40))
            self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        OtpChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=40))
        r = self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data["error"]["code"], "otp_limit_phone")

    def test_only_newest_code_works(self):
        self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        first = last_code("9876543210")
        OtpChallenge.objects.update(created_at=timezone.now() - timedelta(seconds=40))
        self.c.post("/api/auth/otp/request", {"phone": "9876543210"}, format="json")
        second = last_code("9876543210")
        if first != second:
            r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": first, "device_id": DEVICE, "consent": True}, format="json")
            self.assertEqual(r.status_code, 400)
        r = self.c.post("/api/auth/otp/verify", {"phone": "9876543210", "code": second, "device_id": DEVICE, "consent": True}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_voice_channel_reads_digits(self):
        self.c.post("/api/auth/otp/request", {"phone": "9876543210", "channel": "voice"}, format="json")
        m = MemoryBackend.outbox[-1]
        self.assertEqual(m["channel"], "voice")
        self.assertIn(" ".join(m["code"]), m["text"])

    def test_bad_phone_is_validation_error(self):
        r = self.c.post("/api/auth/otp/request", {"phone": "123"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["error"]["code"], "validation_error")


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class SessionTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.c = APIClient()
        self.session = login(self.c).data

    def test_me_requires_auth(self):
        self.assertEqual(APIClient().get("/api/me").status_code, 401)
        r = authed(self.session["access"]).get("/api/me")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["phone"], "9876543210")

    def test_refresh_rotates_and_old_token_is_dead(self):
        old = self.session["refresh"]
        r = self.c.post("/api/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.data["refresh"], old)
        # replaying the old token is treated as theft: the device is revoked
        replay = self.c.post("/api/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(replay.status_code, 401)
        newer = self.c.post("/api/auth/token/refresh", {"refresh": r.data["refresh"]}, format="json")
        self.assertEqual(newer.status_code, 401)
        self.assertTrue(AuditEvent.objects.filter(action="refresh_reuse_detected").exists())
        self.assertEqual(authed(r.data["access"]).get("/api/me").status_code, 401)

    def test_garbage_refresh(self):
        self.assertEqual(self.c.post("/api/auth/token/refresh", {"refresh": "nope"}, format="json").status_code, 401)
        self.assertEqual(self.c.post("/api/auth/token/refresh", {}, format="json").status_code, 401)

    def test_expired_refresh(self):
        Device.objects.update(refresh_expires_at=timezone.now() - timedelta(days=1))
        r = self.c.post("/api/auth/token/refresh", {"refresh": self.session["refresh"]}, format="json")
        self.assertEqual(r.status_code, 401)

    @override_settings(ACCESS_TOKEN_TTL_SECONDS=-10)
    def test_expired_access_token(self):
        s = login(APIClient(), phone="9111111111", device="device-cccc-3333").data
        self.assertEqual(authed(s["access"]).get("/api/me").status_code, 401)

    def test_tampered_access_token(self):
        bad = self.session["access"][:-3] + "abc"
        self.assertEqual(authed(bad).get("/api/me").status_code, 401)

    def test_logout_revokes_device_immediately(self):
        a = authed(self.session["access"])
        self.assertEqual(a.post("/api/auth/logout").status_code, 204)
        self.assertEqual(a.get("/api/me").status_code, 401)

    def test_new_device_notifies_and_lists_devices(self):
        MemoryBackend.outbox.clear()
        OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
        s2 = login(APIClient(), device="device-dddd-4444", device_name="Second phone").data
        self.assertTrue(AuditEvent.objects.filter(action="new_device_login").exists())
        self.assertTrue(any("new phone" in m["text"] for m in MemoryBackend.outbox))
        rows = authed(s2["access"]).get("/api/auth/devices").data["devices"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["current"] for r in rows].count(True), 1)

    def test_owner_can_sign_out_another_device(self):
        OtpChallenge.objects.all().update(created_at=timezone.now() - timedelta(minutes=5))
        s2 = login(APIClient(), device="device-dddd-4444").data
        a2 = authed(s2["access"])
        first_id = self.session["device_id"]
        self.assertEqual(a2.delete(f"/api/auth/devices/{first_id}").status_code, 204)
        self.assertEqual(authed(self.session["access"]).get("/api/me").status_code, 401)
        self.assertEqual(a2.get("/api/me").status_code, 200)

    def test_cannot_revoke_someone_elses_device(self):
        other = login(APIClient(), phone="9222222222", device="device-eeee-5555").data
        r = authed(self.session["access"]).delete(f"/api/auth/devices/{other['device_id']}")
        self.assertEqual(r.status_code, 404)


@override_settings(OTP_BACKEND="accounts.messaging.MemoryBackend")
class PinTests(TestCase):
    def setUp(self):
        MemoryBackend.outbox.clear()
        self.c = APIClient()
        self.session = login(self.c).data
        self.auth = authed(self.session["access"])

    def test_pin_must_be_four_digits(self):
        for bad in ["123", "12345", "abcd", ""]:
            self.assertEqual(self.auth.post("/api/auth/pin", {"pin": bad}, format="json").status_code, 400)

    def test_pin_login_on_same_device(self):
        self.auth.post("/api/auth/pin", {"pin": "4321"}, format="json")
        r = self.c.post("/api/auth/pin/login", {"phone": "9876543210", "device_id": DEVICE, "pin": "4321"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)

    def test_pin_never_works_on_new_device(self):
        self.auth.post("/api/auth/pin", {"pin": "4321"}, format="json")
        r = self.c.post("/api/auth/pin/login", {"phone": "9876543210", "device_id": "device-zzzz-9999", "pin": "4321"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_pin_lockout(self):
        self.auth.post("/api/auth/pin", {"pin": "4321"}, format="json")
        for _ in range(5):
            r = self.c.post("/api/auth/pin/login", {"phone": "9876543210", "device_id": DEVICE, "pin": "0000"}, format="json")
            self.assertEqual(r.status_code, 401)
        r = self.c.post("/api/auth/pin/login", {"phone": "9876543210", "device_id": DEVICE, "pin": "4321"}, format="json")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data["error"]["code"], "pin_locked")

    def test_pin_login_without_pin_or_unknown_user_looks_the_same(self):
        a = self.c.post("/api/auth/pin/login", {"phone": "9876543210", "device_id": DEVICE, "pin": "1111"}, format="json")
        b = self.c.post("/api/auth/pin/login", {"phone": "9000000000", "device_id": DEVICE, "pin": "1111"}, format="json")
        self.assertEqual(a.status_code, b.status_code)
        self.assertEqual(a.data, b.data)

    def test_pin_is_stored_hashed(self):
        self.auth.post("/api/auth/pin", {"pin": "4321"}, format="json")
        self.assertNotIn("4321", User.objects.get(phone="9876543210").pin_hash)


class StaticTrialCodeTests(TestCase):
    """Until a message provider is connected, farmers and buyers use a fixed code; staff never do."""

    def setUp(self):
        MemoryBackend.outbox.clear()

    @override_settings(OTP_STATIC_CODE="123456", OTP_BACKEND="accounts.messaging.MemoryBackend")
    def test_new_number_signs_in_with_fixed_code_and_nothing_is_sent(self):
        otp.request_otp("9111111111", "sms", None)
        self.assertEqual(MemoryBackend.outbox, [])
        otp.verify_code("9111111111", "123456")

    @override_settings(OTP_STATIC_CODE="123456", OTP_BACKEND="accounts.messaging.MemoryBackend")
    def test_admins_and_agronomists_still_get_a_random_code(self):
        for role, phone in ((Role.AGRONOMIST, "9111111112"), (Role.ADMIN, "9111111113")):
            User.objects.create_user(phone=phone, role=role)
            otp.request_otp(phone, "sms", None)
            self.assertEqual(len(MemoryBackend.outbox), 1)
            MemoryBackend.outbox.clear()

    @override_settings(OTP_STATIC_CODE="", OTP_BACKEND="accounts.messaging.MemoryBackend")
    def test_empty_setting_turns_it_off(self):
        otp.request_otp("9111111114", "sms", None)
        self.assertEqual(len(MemoryBackend.outbox), 1)

    @override_settings(OTP_STATIC_CODE="123456", OTP_BACKEND="accounts.messaging.MemoryBackend")
    def test_fpo_agents_use_the_fixed_code(self):
        User.objects.create_user(phone="9111111115", role=Role.AGENT)
        otp.request_otp("9111111115", "sms", None)
        self.assertEqual(MemoryBackend.outbox, [])
        otp.verify_code("9111111115", "123456")
