from rest_framework.test import APIClient

from accounts.messaging import MemoryBackend

DEVICE = "device-aaaa-1111"


def last_code(phone):
    for m in reversed(MemoryBackend.outbox):
        if m["phone"] == phone and m["code"]:
            return m["code"]
    raise AssertionError("no OTP sent")


def login(client, phone="9876543210", device=DEVICE, role="farmer", **extra):
    r = client.post("/api/auth/otp/request", {"phone": phone}, format="json")
    assert r.status_code == 200, r.content
    body = {"phone": phone, "code": last_code(phone), "device_id": device, "consent": True, "role": role, **extra}
    return client.post("/api/auth/otp/verify", body, format="json")


def authed(access):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return c
