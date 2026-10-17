

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import audit, messaging, otp, tokens
from .errors import ApiError
from .models import Device, Language, Role, User, UserStatus
from .phone import InvalidPhone, normalise_phone


class PhoneField(serializers.CharField):
    def to_internal_value(self, data):
        raw = super().to_internal_value(data)
        try:
            return normalise_phone(raw)
        except InvalidPhone as e:
            raise serializers.ValidationError(str(e))


class OtpRequestSerializer(serializers.Serializer):
    phone = PhoneField()
    channel = serializers.ChoiceField(choices=["sms", "whatsapp", "voice"], default="sms")
    language = serializers.ChoiceField(choices=Language.values, default="hi")


class OtpVerifySerializer(serializers.Serializer):
    phone = PhoneField()
    code = serializers.CharField(max_length=12)
    device_id = serializers.CharField(min_length=8, max_length=64)
    device_name = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=[Role.FARMER, Role.BUYER], default=Role.FARMER)
    language = serializers.ChoiceField(choices=Language.values, required=False)
    consent = serializers.BooleanField()

    def validate_consent(self, value):
        if value is not True:
            raise serializers.ValidationError("Consent is required to continue")
        return value


def user_summary(user: User) -> dict:
    out = {"id": user.pk, "phone": user.phone, "role": user.role, "language": user.language, "status": user.status}
    profile = getattr(user, "farmer_profile", None) or getattr(user, "buyer_profile", None)
    out["level"] = getattr(profile, "level", 0) if profile else 0
    out["has_pin"] = bool(user.pin_hash)
    return out


class OtpRequestView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        s = OtpRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        result = otp.request_otp(d["phone"], d["channel"], audit.client_ip(request), d["language"])
        return Response(result)


class OtpVerifyView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        s = OtpVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        # Outside any transaction on purpose: a wrong guess must stay counted even though the request fails.
        otp.verify_code(d["phone"], d["code"])
        with transaction.atomic():
            return self._sign_in(request, d)

    def _sign_in(self, request, d):
        now = timezone.now()
        user = User.objects.filter(phone=d["phone"]).first()
        is_new = False
        if user is None:
            user = User.objects.create_user(
                phone=d["phone"], role=d["role"], language=d.get("language", Language.HINDI),
                status=UserStatus.ACTIVE, consented_at=now, consent_version=settings.CONSENT_VERSION,
            )
            is_new = True
            audit.log("user_created", actor=user, target=user, request=request, via="self")
        elif user.status == UserStatus.PENDING:
            # Assisted onboarding: the farmer confirms on their own phone and takes ownership.
            user.status = UserStatus.ACTIVE
            user.consented_at = now
            user.consent_version = settings.CONSENT_VERSION
            if d.get("language"):
                user.language = d["language"]
            user.save(update_fields=["status", "consented_at", "consent_version", "language"])
            audit.log("owner_confirmed", actor=user, target=user, request=request)
            from profiles import services  # lazy: profiles depends on accounts
            services.on_owner_confirmed(user)
        if not user.is_active:
            raise ApiError("account_unavailable", "This account is not available", 403)

        had_other_devices = user.devices.filter(revoked_at__isnull=True).exists()
        device, created = Device.objects.get_or_create(user=user, device_id=d["device_id"], defaults={"name": d["device_name"]})
        if not created:
            device.revoked_at = None  # a fresh OTP re-opens a device the owner had signed out
            if d["device_name"]:
                device.name = d["device_name"]
            device.save(update_fields=["revoked_at", "name"])
        if created and had_other_devices:
            audit.log("new_device_login", actor=user, target=device, request=request, device_name=device.name)
            messaging.send_notice(user.phone, "Seedha Bazar: your account was opened on a new phone. If this was not you, sign out other phones in the app.")
        audit.log("login_success", actor=user, target=device, request=request, method="otp")
        body = tokens.issue(device)
        body["user"] = user_summary(user)
        body["is_new_user"] = is_new
        return Response(body, status=status.HTTP_201_CREATED if is_new else status.HTTP_200_OK)


class RefreshView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        rt = request.data.get("refresh")
        if not isinstance(rt, str) or not rt:
            raise ApiError("invalid_refresh", "Please sign in again", 401)
        return Response(tokens.refresh(rt, request))


class PinSetSerializer(serializers.Serializer):
    pin = serializers.RegexField(r"^\d{4}$", error_messages={"invalid": "PIN must be exactly 4 digits"})


class PinSetView(APIView):
    def post(self, request):
        s = PinSetSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        u = request.user
        u.pin_hash = make_password(s.validated_data["pin"])
        u.pin_failed = 0
        u.pin_locked_until = None
        u.save(update_fields=["pin_hash", "pin_failed", "pin_locked_until"])
        audit.log("pin_set", actor=u, target=u, request=request)
        return Response({"has_pin": True})

    def delete(self, request):
        u = request.user
        u.pin_hash = ""
        u.save(update_fields=["pin_hash"])
        audit.log("pin_removed", actor=u, target=u, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PinLoginSerializer(serializers.Serializer):
    phone = PhoneField()
    device_id = serializers.CharField(min_length=8, max_length=64)
    pin = serializers.CharField(max_length=8)


class PinLoginView(APIView):
    """Quick re-entry on a phone that has already signed in with an OTP. Never works on a new device."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        s = PinLoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        generic = ApiError("invalid_pin_login", "Could not sign in with PIN. Use an OTP instead.", 401)
        user = User.objects.filter(phone=d["phone"]).first()
        if user is None or not user.pin_hash or not user.is_active or user.status != UserStatus.ACTIVE:
            raise generic
        now = timezone.now()
        if user.pin_locked_until and user.pin_locked_until > now:
            wait = int((user.pin_locked_until - now).total_seconds())
            raise ApiError("pin_locked", "PIN is locked for a while. Use an OTP instead.", 429, retry_after=wait)
        device = Device.objects.filter(user=user, device_id=d["device_id"], revoked_at__isnull=True).first()
        if device is None or (device.refresh_expires_at and device.refresh_expires_at < now):
            raise generic
        if not check_password(d["pin"], user.pin_hash):
            user.pin_failed += 1
            if user.pin_failed >= settings.PIN_MAX_WRONG_ATTEMPTS:
                user.pin_locked_until = now + timedelta(minutes=settings.PIN_LOCK_MINUTES)
                user.pin_failed = 0
                audit.log("pin_locked", actor=user, target=user, request=request)
            user.save(update_fields=["pin_failed", "pin_locked_until"])
            raise generic
        user.pin_failed = 0
        user.save(update_fields=["pin_failed"])
        audit.log("login_success", actor=user, target=device, request=request, method="pin")
        body = tokens.issue(device)
        body["user"] = user_summary(user)
        return Response(body)


class DeviceListView(APIView):
    def get(self, request):
        current = request.device.pk
        rows = [
            {"id": str(d.pk), "name": d.name, "created_at": d.created_at, "last_used_at": d.last_used_at, "current": d.pk == current}
            for d in request.user.devices.filter(revoked_at__isnull=True).order_by("-last_used_at")
        ]
        return Response({"devices": rows})


class DeviceDetailView(APIView):
    def delete(self, request, device_pk):
        d = request.user.devices.filter(pk=device_pk, revoked_at__isnull=True).first()
        if d is None:
            raise ApiError("not_found", "Device not found", 404)
        d.revoked_at = timezone.now()
        d.save(update_fields=["revoked_at"])
        audit.log("device_revoked", actor=request.user, target=d, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    def post(self, request):
        d = request.device
        d.revoked_at = timezone.now()
        d.save(update_fields=["revoked_at"])
        audit.log("logout", actor=request.user, target=d, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
