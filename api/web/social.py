"""Continue with Facebook. Seedha Bazar accounts belong to a mobile number (farmers need SMS), so the first time someone
uses Facebook we ask for their number once and link the two; after that, Facebook alone signs them in.

Setup: create an app at developers.facebook.com (Facebook Login for Business or Facebook Login), add the redirect URL
<SITE_URL>/auth/facebook/callback/, set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET, then switch it on in Console > Settings.
"""
import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth import login
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts import audit, sessions
from accounts.models import SitePolicy, SocialLogin
from config.netutil import ssl_context

from .context import home_for
from .helpers import ok, warn


def enabled() -> bool:
    return bool(settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET) and SitePolicy.current().facebook_login


def _redirect_uri(request) -> str:
    return f"{settings.SITE_URL.rstrip('/')}/auth/facebook/callback/"


def _graph(path: str, params: dict) -> dict:
    url = f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15, context=ssl_context()) as r:  # noqa: S310 - fixed Facebook host
        return json.loads(r.read())


def start(request):
    if not enabled():
        raise Http404
    state = secrets.token_urlsafe(24)
    request.session["fb_state"] = state
    request.session["login_as"] = request.GET.get("as", request.session.get("login_as", "farmer"))
    q = urllib.parse.urlencode({"client_id": settings.FACEBOOK_APP_ID, "redirect_uri": _redirect_uri(request), "state": state, "scope": "public_profile,email",
                                "response_type": "code"})
    return redirect(f"https://www.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/dialog/oauth?{q}")


def fetch_identity(code: str, redirect_uri: str) -> dict:
    tok = _graph("oauth/access_token", {"client_id": settings.FACEBOOK_APP_ID, "client_secret": settings.FACEBOOK_APP_SECRET, "redirect_uri": redirect_uri, "code": code})
    access = tok["access_token"]
    proof = hmac.new(settings.FACEBOOK_APP_SECRET.encode(), access.encode(), hashlib.sha256).hexdigest()
    me = _graph("me", {"fields": "id,name,email", "access_token": access, "appsecret_proof": proof})
    return {"uid": me["id"], "name": me.get("name", ""), "email": me.get("email", "")}


def callback(request):
    if not enabled():
        raise Http404
    if request.GET.get("error") or not request.GET.get("code") or request.GET.get("state") != request.session.pop("fb_state", None):
        warn(request, "Facebook sign-in was cancelled or did not work. Use your phone number instead.")
        return redirect("/login/")
    try:
        ident = fetch_identity(request.GET["code"], _redirect_uri(request))
    except Exception:
        warn(request, "Facebook sign-in was cancelled or did not work. Use your phone number instead.")
        return redirect("/login/")
    link = SocialLogin.objects.filter(provider="facebook", uid=ident["uid"]).select_related("user").first()
    if link and link.user.is_active:
        user = link.user
        login(request, user)
        sessions.start(request, user, "facebook")
        link.last_login = timezone.now()
        link.save(update_fields=["last_login"])
        audit.log("login_success", actor=user, target=user, request=request, method="facebook")
        return redirect(home_for(user))
    request.session["link_facebook"] = ident
    ok(request, "Facebook account found. Now enter your mobile number once to link it. Next time Facebook alone signs you in.")
    return redirect("/login/")


def link(user, ident: dict, request=None):
    SocialLogin.objects.update_or_create(provider="facebook", uid=ident["uid"], defaults={"user": user, "name": ident.get("name", "")[:160],
                                                                                        "email": (ident.get("email") or "")[:254], "last_login": timezone.now()})
    fp = getattr(user, "farmer_profile", None)
    if fp is not None and not fp.name and ident.get("name"):
        fp.name = ident["name"][:120]
        fp.save()
    audit.log("facebook_linked", actor=user, target=user, request=request)


@require_POST
def unlink(request):
    if request.user.is_authenticated:
        SocialLogin.objects.filter(user=request.user, provider="facebook").delete()
        ok(request, "Facebook is no longer linked to your account.")
    return redirect(home_for(request.user))


def _parse_signed_request(sr: str) -> dict | None:
    try:
        sig, payload = sr.split(".", 1)
        pad = lambda s: s + "=" * (-len(s) % 4)
        expected = hmac.new(settings.FACEBOOK_APP_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(base64.urlsafe_b64decode(pad(sig)), expected):
            return None
        return json.loads(base64.urlsafe_b64decode(pad(payload)))
    except Exception:
        return None


@csrf_exempt
@require_POST
def data_deletion(request):
    """Facebook's required data-deletion callback: remove the link to that Facebook account."""
    data = _parse_signed_request(request.POST.get("signed_request", ""))
    if not data or "user_id" not in data:
        return JsonResponse({"error": "bad request"}, status=400)
    n, _ = SocialLogin.objects.filter(provider="facebook", uid=str(data["user_id"])).delete()
    code = secrets.token_hex(8)
    audit.log("facebook_data_deleted", actor=None, target=None, removed=n, code=code)
    return JsonResponse({"url": f"{settings.SITE_URL}/privacy/", "confirmation_code": code})
