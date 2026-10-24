import time

from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from accounts import audit, otp, signin
from accounts.errors import ApiError
from accounts.models import Role
from django.conf import settings

from . import location
from .context import home_for
from .forms import CodeForm, ConsentForm, PhoneForm
from .helpers import error_text, ok, warn

ROLE_FOR = {"farmer": Role.FARMER, "buyer": Role.BUYER, "fpo": Role.AGENT}
CHANNELS = ("sms", "whatsapp", "voice")
STEP_LIFETIME = 15 * 60


def _pending(request):
    """The phone that is mid-login, or None if the step has gone stale."""
    st = request.session.get("login")
    if not st or time.time() - st.get("t", 0) > STEP_LIFETIME:
        return None
    return st


def _safe_next(request, target):
    ok = target and target.startswith("/") and not target.startswith("//") and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()})
    return target if ok else ""


@ensure_csrf_cookie
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_next(request, request.GET.get("next")) or home_for(request.user))
    if request.GET.get("next") is not None:
        request.session["login_next"] = _safe_next(request, request.GET["next"])
    door = request.GET.get("as") or request.session.get("login_as") or "farmer"
    if door not in ROLE_FOR:
        door = "farmer"
    request.session["login_as"] = door
    form = PhoneForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        channel = request.POST.get("channel", "sms")
        if channel not in settings.OTP_CHANNELS:
            channel = "sms"
        try:
            otp.request_otp(form.cleaned_data["phone"], channel, audit.client_ip(request), request.lang)
        except ApiError as e:
            form.add_error("phone", error_text(request, e))
        else:
            request.session["login"] = {"phone": form.cleaned_data["phone"], "t": time.time(), "channel": channel}
            return redirect("/login/verify/")
    loc = location.current(request)
    return render(request, "web/login.html", {"form": form, "door": door, "channels": [c for c in CHANNELS if c in settings.OTP_CHANNELS],
                                              "loc": loc, "loc_label": location.label(loc)})


def verify_view(request):
    st = _pending(request)
    if st is None:
        return redirect("/login/")
    form = CodeForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        try:
            otp.verify_code(st["phone"], form.cleaned_data["code"])
        except ApiError as e:
            form.add_error("code", error_text(request, e))
        else:
            if signin.needs_consent(st["phone"]):
                request.session["login"] = {**st, "verified": True, "t": time.time()}
                return redirect("/login/consent/")
            return _finish(request, st["phone"])
    return render(request, "web/verify.html", {"form": form, "phone": st["phone"]})


@require_POST
def resend_view(request):
    st = _pending(request)
    if st is None:
        return redirect("/login/")
    channel = request.POST.get("channel", st.get("channel", "sms"))
    if channel not in settings.OTP_CHANNELS:
        channel = "sms"
    try:
        otp.request_otp(st["phone"], channel, audit.client_ip(request), request.lang)
        request.session["login"] = {**st, "t": time.time(), "channel": channel}
        ok(request, "A new code is on its way.")
    except ApiError as e:
        messages.error(request, error_text(request, e))
    return redirect("/login/verify/")


def consent_view(request):
    st = _pending(request)
    if st is None or not st.get("verified"):
        return redirect("/login/")
    form = ConsentForm(request.POST or None, lang=request.lang)
    if request.method == "POST" and form.is_valid():
        return _finish(request, st["phone"])
    return render(request, "web/consent.html", {"form": form})


def _finish(request, phone):
    door = request.session.get("login_as", "farmer")
    lang = request.lang
    try:
        user, is_new = signin.open_account(phone, ROLE_FOR.get(door, Role.FARMER), lang, request)
    except ApiError as e:
        messages.error(request, error_text(request, e))
        return redirect("/login/")
    keep = {k: request.session.get(k) for k in ("lang", "join_code", "attribution", "loc", "login_next") if request.session.get(k)}
    request.session.pop("login", None)
    login(request, user)
    request.session.update(keep)
    audit.log("login_success", actor=user, target=user, request=request, method="otp-web")
    if door == "fpo" and user.role != Role.AGENT:
        warn(request, "This number is already a farmer or buyer account. To register an FPO, use a different number.")
    code = request.session.pop("join_code", None)
    if code and user.role == Role.FARMER:
        _join_from_link(request, user, code)
    loc = request.session.get("loc")
    if loc:  # a place shared before signing in goes onto an empty farmer profile
        location.remember(request, loc.get("state", ""), loc.get("district", ""), loc.get("src", "gps"))
    nxt = _safe_next(request, request.session.pop("login_next", ""))
    return redirect(nxt or home_for(user))


def _join_from_link(request, user, code):
    from profiles import services
    try:
        link = services.request_join(user.farmer_profile, code, request)
        if link.status == "approved":
            ok(request, "You are now a member of {org}.", org=link.organisation.name)
        else:
            ok(request, "Your request was sent to {org}. They will confirm you.", org=link.organisation.name)
    except ApiError as e:
        if e.code != "already_member":
            messages.error(request, error_text(request, e))


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        audit.log("logout", actor=request.user, target=request.user, request=request, method="web")
    lang = request.session.get("lang")
    logout(request)
    if lang:
        request.session["lang"] = lang
    return redirect("/")


def go_view(request):
    return redirect(home_for(request.user))
