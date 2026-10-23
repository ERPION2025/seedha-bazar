import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from notify import service as notify
from rates import calc, services
from rates.crops import CROPS, EMOJI
from rates.fmt import inr
from rates.models import RateAlert
from rates.serialize import quote_json

from . import location
from .calc_strings import js_strings
from .helpers import ok, warn
from .i18n import tr

LANG_TAG = {"hi": "hi-IN", "mr": "mr-IN", "en": "en-IN"}


def rate_context(request, limit: int = 6) -> dict:
    """What the 'today's mandi rates' strip needs: crops with a typical price for the visitor's place (or the default state)."""
    from django.conf import settings

    loc = location.current(request)
    state = loc.get("state") or settings.DEFAULT_STATE
    rows = services.crop_prices(state, loc.get("district", ""))[:limit]
    return {"strip": [{**r, "label": CROPS[r["crop"]], "emoji": EMOJI.get(r["crop"], "🌾")} for r in rows], "strip_loc": loc,
            "loc": loc, "loc_label": location.label(loc), "strip_place": location.label(loc) or state, "strip_known": bool(loc), "rates_updated": services.last_update()}


@ensure_csrf_cookie
def rates_page(request):
    loc = location.current(request)
    tiles = services.crop_prices(loc.get("state", ""), loc.get("district", ""))
    crop = request.GET.get("crop", "")
    if crop not in CROPS:
        crop = tiles[0]["crop"] if tiles else ""
    q = services.quote(crop, loc.get("state", ""), loc.get("district", "")) if crop else None
    return render(request, "web/public/rates.html", {
        "loc": loc, "loc_label": location.label(loc), "tiles": [{**t, "label": CROPS[t["crop"]], "emoji": EMOJI.get(t["crop"], "🌾")} for t in tiles],
        "crop": crop, "q": q, "updated": services.last_update(), "alert_set": request.user.is_authenticated and request.user.rate_alerts.filter(crop=crop, active=True).exists() if crop else False,
    })


def quote_json_view(request):
    loc = location.current(request)
    crop = request.GET.get("crop", "")
    if crop not in CROPS:
        return JsonResponse({"error": "unknown_crop"}, status=400)
    q = services.quote(crop, request.GET.get("state", loc.get("state", "")), request.GET.get("district", loc.get("district", "")))
    return JsonResponse(quote_json(q))


def summary_json_view(request):
    loc = location.current(request)
    rows = services.crop_prices(request.GET.get("state", loc.get("state", "")), request.GET.get("district", loc.get("district", "")))
    return JsonResponse({"crops": [{"crop": r["crop"], "label": CROPS[r["crop"]], "emoji": EMOJI.get(r["crop"], "🌾"), "typical": int(r["typical"]),
                                    "as_of": r["as_of"].isoformat() if r["as_of"] else None, "scope": r["scope"]} for r in rows]})


def places_json_view(request):
    return JsonResponse({"places": location.known_places()})


@ensure_csrf_cookie
def calculator(request):
    from .forms import LeadForm

    loc = location.current(request)
    tiles = services.crop_prices(loc.get("state", ""), loc.get("district", ""))
    priced = {t["crop"]: t for t in tiles}
    crops = [{"crop": k, "label": tr(request.lang, v), "emoji": EMOJI.get(k, "🌾"), "typical": int(priced[k]["typical"]) if k in priced else None}
             for k, v in CROPS.items()]
    crops.sort(key=lambda c: (c["typical"] is None, list(priced).index(c["crop"]) if c["crop"] in priced else 0))
    u = request.user
    data = {
        "crops": crops, "loc": loc, "lang": request.lang, "speech": LANG_TAG[request.lang], "strings": js_strings(request.lang),
        "user": {"in": u.is_authenticated, "role": getattr(u, "role", ""), "phone": u.phone if u.is_authenticated else ""},
        "preset": {k: request.GET.get(k, "") for k in ("crop", "qty", "unit")},
    }
    return render(request, "web/public/calculator.html", {"data": data, "loc_label": location.label(loc), "loc": loc, "form": LeadForm(lang=request.lang)})


def _number(raw, cap=10**9) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return v if 0 < v <= cap else 0.0


@require_POST
def calculator_send(request):
    """Send the person their own result by SMS or WhatsApp. The sums are redone here; only numbers come from the browser."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "sign_in"}, status=401)
    try:
        body = json.loads(request.body or b"{}")
        inp = body["inputs"]
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    channel = body.get("channel")
    if channel not in ("sms", "whatsapp"):
        return JsonResponse({"ok": False, "error": "bad_channel"}, status=400)
    crop = inp.get("crop") if inp.get("crop") in CROPS else None
    clean = {"qty": _number(inp.get("qty")), "unit": inp.get("unit") if inp.get("unit") in ("kg", "quintal", "tonne", "bag") else "quintal",
             "bagKg": _number(inp.get("bagKg"), 500), "rate": _number(inp.get("rate")), "rateUnit": "kg" if inp.get("rateUnit") == "kg" else "quintal",
             "commissionPct": min(_number(inp.get("commissionPct"), 100), 100), "fees": _number(inp.get("fees")), "other": _number(inp.get("other")),
             "transport": _number(inp.get("transport")), "directRate": _number(inp.get("directRate")), "directTransport": _number(inp.get("directTransport"))}
    if not (crop and clean["qty"] and clean["rate"]):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    r = calc.compute(clean)
    lang = request.lang
    unit_label = tr(lang, clean["unit"])
    qty = f"{clean['qty']:g} {unit_label}"
    params = {"crop": tr(lang, CROPS[crop]), "qty": qty, "hand": inr(r["hand"]), "cut": inr(r["cut"])}
    template = "calc_result"
    if "direct" in r:
        template = "calc_result_direct"
        params.update(direct=inr(r["direct"]), gap=inr(abs(r["gap"])))
    msg = notify.send(channel, request.user.phone, template, lang, user=request.user, related="calculator", **params)
    delivered = msg.status == "sent"
    blocked = msg.status == "blocked"
    return JsonResponse({
        "ok": not blocked and msg.status != "failed", "delivered": delivered, "status": msg.status,
        "wa_url": notify.wa_link(msg.text, request.user.phone), "sms_url": notify.sms_link(msg.text, request.user.phone),
    })


@require_POST
@login_required(login_url="/login/")
def alert_create(request):
    loc = location.current(request)
    try:
        body = json.loads(request.body or b"{}") if request.content_type == "application/json" else request.POST
    except ValueError:
        body = {}
    crop, channel = body.get("crop", ""), body.get("channel", "whatsapp")
    if crop not in CROPS or channel not in ("sms", "whatsapp"):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    RateAlert.objects.update_or_create(user=request.user, crop=crop, channel=channel, defaults={
        "state": loc.get("state", ""), "district": loc.get("district", ""), "language": request.lang, "active": True})
    return JsonResponse({"ok": True, "live": notify.backend_for(channel).delivers})


@login_required(login_url="/login/")
def alerts_page(request):
    return render(request, "web/alerts.html", {"alerts": request.user.rate_alerts.all().order_by("crop"), "live": {c: notify.backend_for(c).delivers for c in ("sms", "whatsapp")}})


@require_POST
@login_required(login_url="/login/")
def alert_delete(request, pk):
    get_object_or_404(RateAlert, pk=pk, user=request.user).delete()
    ok(request, "Removed.")
    return redirect("/alerts/")
