"""Web sign-in sessions: record each one, and keep at most SitePolicy.max_sessions per person (the oldest is signed out)."""
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.utils import timezone

from . import audit
from .models import LoginSession, SitePolicy

SEEN_EVERY = timedelta(minutes=5)


def start(request, user, method: str = "otp") -> LoginSession:
    policy = SitePolicy.current()
    request.session.set_expiry(policy.session_days * 86400)
    if not request.session.session_key:
        request.session.save()
    ls = LoginSession.objects.create(user=user, session_key=request.session.session_key, method=method, ip=audit.client_ip(request),
                                     user_agent=request.META.get("HTTP_USER_AGENT", "")[:300])
    enforce(user, policy.max_sessions, keep=ls)
    return ls


def enforce(user, limit: int, keep: LoginSession | None = None) -> int:
    """Sign out the oldest sessions beyond `limit`. Returns how many were ended."""
    active = list(LoginSession.objects.filter(user=user, ended_at__isnull=True).order_by("-created_at"))
    extra = [s for s in active if s != keep][max(0, limit - (1 if keep else 0)):] if limit else []
    for s in extra:
        end(s, "limit")
    return len(extra)


def end(ls: LoginSession, reason: str):
    Session.objects.filter(session_key=ls.session_key).delete()
    ls.ended_at, ls.end_reason = timezone.now(), reason
    ls.save(update_fields=["ended_at", "end_reason"])
    audit.log("session_ended", actor=None, target=ls.user, reason=reason)


def end_current(request, reason: str = "logout"):
    key = request.session.session_key
    if key:
        LoginSession.objects.filter(session_key=key, ended_at__isnull=True).update(ended_at=timezone.now(), end_reason=reason)


class SessionGuardMiddleware:
    """Keeps a record for every signed-in browser and notes when it was last used."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and hasattr(request, "session"):
            key = request.session.session_key
            if key:
                ls = LoginSession.objects.filter(session_key=key).order_by("-created_at").first()
                now = timezone.now()
                if ls is None:
                    LoginSession.objects.create(user=user, session_key=key, method=LoginSession.Method.EXISTING, ip=audit.client_ip(request),
                                                user_agent=request.META.get("HTTP_USER_AGENT", "")[:300])
                elif now - ls.last_seen > SEEN_EVERY:
                    LoginSession.objects.filter(pk=ls.pk).update(last_seen=now)
        return self.get_response(request)
