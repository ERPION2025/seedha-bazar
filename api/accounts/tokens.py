import hashlib
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from . import audit
from .errors import ApiError
from .models import Device


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _access_token(device: Device) -> str:
    now = timezone.now()
    payload = {
        "sub": str(device.user_id),
        "did": str(device.id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_access(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"], options={"require": ["exp", "sub", "did"]})


def issue(device: Device) -> dict:
    """Give the device a fresh access token and a rotated refresh token."""
    refresh = secrets.token_urlsafe(48)
    device.prev_refresh_hash = device.refresh_hash
    device.refresh_hash = _sha(refresh)
    device.refresh_expires_at = timezone.now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
    device.last_used_at = timezone.now()
    device.save(update_fields=["prev_refresh_hash", "refresh_hash", "refresh_expires_at", "last_used_at"])
    return {"access": _access_token(device), "refresh": refresh, "expires_in": settings.ACCESS_TOKEN_TTL_SECONDS, "device_id": str(device.id)}


def refresh(refresh_token: str, request=None) -> dict:
    h = _sha(refresh_token or "")
    bad = ApiError("invalid_refresh", "Please sign in again", 401)
    device = Device.objects.select_related("user").filter(refresh_hash=h).first()
    if device is None:
        # An already-used refresh token means it may have been copied: kill that device.
        stale = Device.objects.select_related("user").filter(prev_refresh_hash=h, revoked_at__isnull=True).first()
        if stale:
            stale.revoked_at = timezone.now()
            stale.save(update_fields=["revoked_at"])
            audit.log("refresh_reuse_detected", actor=stale.user, target=stale, request=request)
        raise bad
    if not device.is_active or not device.user.is_active:
        raise bad
    if device.refresh_expires_at and device.refresh_expires_at < timezone.now():
        raise bad
    return issue(device)
