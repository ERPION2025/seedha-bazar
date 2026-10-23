import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import status

from . import messaging
from .errors import ApiError
from .models import OtpChallenge, Role, User

CHANNELS = {"sms", "whatsapp", "voice"}


def _hash(phone: str, code: str) -> str:
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def static_code_for(phone: str) -> str | None:
    """The pilot's fixed code, for farmers, buyers, FPO agents and not-yet-registered numbers. Never for admins or agronomists."""
    fixed = settings.OTP_STATIC_CODE
    if not fixed:
        return None
    role = User.objects.filter(phone=phone).values_list("role", flat=True).first()
    return fixed if role in (None, Role.FARMER, Role.BUYER, Role.AGENT) else None


def request_otp(phone: str, channel: str, ip: str | None, language: str = "hi") -> dict:
    """Create and send a code. The reply never says whether the number is registered."""
    if channel not in CHANNELS:
        raise ApiError("bad_channel", "Channel must be sms, whatsapp or voice")
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    recent = OtpChallenge.objects.filter(phone=phone, created_at__gte=hour_ago).order_by("-created_at")
    last = recent.first()
    if last:
        wait = settings.OTP_RESEND_COOLDOWN_SECONDS - int((now - last.created_at).total_seconds())
        if wait > 0:
            raise ApiError("otp_cooldown", f"Please wait {wait} seconds before asking again", status.HTTP_429_TOO_MANY_REQUESTS, retry_after=wait)
    if recent.count() >= settings.OTP_MAX_PER_PHONE_PER_HOUR:
        raise ApiError("otp_limit_phone", "Too many codes requested for this number. Try again later.", status.HTTP_429_TOO_MANY_REQUESTS, retry_after=3600)
    if ip and OtpChallenge.objects.filter(ip=ip, created_at__gte=hour_ago).count() >= settings.OTP_MAX_PER_IP_PER_HOUR:
        raise ApiError("otp_limit_ip", "Too many requests from this network. Try again later.", status.HTTP_429_TOO_MANY_REQUESTS, retry_after=3600)

    # Only the newest code is valid.
    OtpChallenge.objects.filter(phone=phone, consumed_at__isnull=True).update(consumed_at=now)

    fixed = static_code_for(phone)
    code = fixed or "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))
    OtpChallenge.objects.create(
        phone=phone,
        code_hash=_hash(phone, code),
        channel=channel,
        ip=ip,
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
    )
    if not fixed:  # a fixed code is public, so there is nothing to deliver
        messaging.send_otp(phone, code, channel, language)
    out = {"sent": True, "channel": channel, "expires_in": settings.OTP_TTL_SECONDS, "resend_in": settings.OTP_RESEND_COOLDOWN_SECONDS}
    if settings.DEBUG and settings.OTP_BACKEND == "console" and not fixed:
        out["dev_code"] = code  # local development only: the website shows it, so testers need not read the server log
    return out


def verify_code(phone: str, code: str) -> None:
    """Raise ApiError unless `code` is the newest valid code for `phone`. Consumes it on success."""
    code = (code or "").strip().translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    now = timezone.now()
    ch = OtpChallenge.objects.filter(phone=phone, consumed_at__isnull=True).order_by("-created_at").first()
    generic = ApiError("invalid_or_expired_code", "The code is wrong or has expired. Ask for a new one.")
    if ch is None or ch.expires_at < now or ch.wrong_attempts >= settings.OTP_MAX_WRONG_ATTEMPTS:
        raise generic
    if not hmac.compare_digest(ch.code_hash, _hash(phone, code)):
        ch.wrong_attempts += 1
        if ch.wrong_attempts >= settings.OTP_MAX_WRONG_ATTEMPTS:
            ch.consumed_at = now  # burn it; the user must request a fresh code
        ch.save(update_fields=["wrong_attempts", "consumed_at"])
        raise generic
    ch.consumed_at = now
    ch.save(update_fields=["consumed_at"])
