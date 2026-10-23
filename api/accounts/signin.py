"""Account opening after a code has been verified. Shared by the JSON API and the website."""
from django.conf import settings
from django.utils import timezone

from . import audit
from .errors import ApiError
from .models import Language, User, UserStatus


def needs_consent(phone: str) -> bool:
    """True when this person must tick the consent box (new, confirming an agent's entry, or text changed)."""
    user = User.objects.filter(phone=phone).first()
    return user is None or user.status == UserStatus.PENDING or user.consent_version != settings.CONSENT_VERSION


def open_account(phone: str, role: str, language: str | None, request=None) -> tuple[User, bool]:
    """Find, create or activate the account for a phone whose code was just verified and who has consented.

    Returns (user, is_new). Raises ApiError if the account is not available.
    """
    now = timezone.now()
    user = User.objects.filter(phone=phone).first()
    is_new = False
    if user is None:
        user = User.objects.create_user(
            phone=phone, role=role, language=language or Language.HINDI,
            status=UserStatus.ACTIVE, consented_at=now, consent_version=settings.CONSENT_VERSION,
        )
        is_new = True
        audit.log("user_created", actor=user, target=user, request=request, via="self")
    elif user.status == UserStatus.PENDING:
        # Assisted onboarding: the farmer confirms on their own phone and takes ownership.
        user.status = UserStatus.ACTIVE
        user.consented_at = now
        user.consent_version = settings.CONSENT_VERSION
        if language:
            user.language = language
        user.save(update_fields=["status", "consented_at", "consent_version", "language"])
        audit.log("owner_confirmed", actor=user, target=user, request=request)
        from profiles import services  # lazy: profiles depends on accounts
        services.on_owner_confirmed(user)
    elif user.is_active and user.consent_version != settings.CONSENT_VERSION:
        user.consented_at = now
        user.consent_version = settings.CONSENT_VERSION
        user.save(update_fields=["consented_at", "consent_version"])
        audit.log("consent_renewed", actor=user, target=user, request=request)
    if not user.is_active:
        raise ApiError("account_unavailable", "This account is not available", 403)
    return user, is_new
