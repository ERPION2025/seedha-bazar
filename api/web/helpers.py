from datetime import date, datetime
from decimal import Decimal
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from accounts.errors import ApiError

from .context import home_for
from .i18n import api_error_text, tr


def flash(request, level, text, **kw):
    messages.add_message(request, level, tr(request.lang, text, **kw))


def ok(request, text, **kw):
    flash(request, messages.SUCCESS, text, **kw)


def warn(request, text, **kw):
    flash(request, messages.WARNING, text, **kw)


def error_text(request, e: ApiError) -> str:
    """An ApiError in the visitor's language. Wait times are filled in from the error itself."""
    if e.code == "insufficient_stock" and "available_kg" in e.extra:
        return tr(request.lang, "Only {kg} kg is in stock for this crop. Record the harvest first.", kg=e.extra["available_kg"])
    text = api_error_text(request.lang, e.code, e.message)
    if e.code == "otp_cooldown" and "retry_after" in e.extra:
        return tr(request.lang, "Please wait {n} seconds before asking again.", n=e.extra["retry_after"])
    return text


def role_required(*roles, staff=False):
    """Signed-in people only; anyone in the wrong area is sent to their own home page."""

    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            u = request.user
            if not u.is_authenticated:
                return redirect("/console/login/" if staff else "/login/")
            allowed = (u.is_staff or u.role == "admin") if staff else u.role in roles
            if not allowed or u.status != "active":
                return redirect(home_for(u))
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def payload(cleaned: dict) -> dict:
    """Form values as the strings the record serializers expect; empty values are left out."""
    out = {}
    for k, v in cleaned.items():
        if v is None or v == "":
            continue
        out[k] = v.isoformat() if isinstance(v, (date, datetime)) else str(v) if isinstance(v, Decimal) else v
    return out
