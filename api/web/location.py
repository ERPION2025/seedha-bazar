"""Where the visitor is, as a state and district the mandi data understands.

Order of trust: a place they chose or allowed this session, then the district on their farmer profile. Only the state and district are kept,
never coordinates.
"""
import json
import time

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from accounts import audit
from rates import geocode, services

MAX_LOOKUPS_PER_HOUR = 30


def known_places() -> dict:
    return cache.get_or_set("rates:places", services.places, 600)


def match(state: str, district: str) -> tuple[str, str]:
    """Names as the mandi data spells them where we can tell, otherwise as given."""
    places = known_places()
    st = next((s for s in places if s.lower() == (state or "").strip().lower()), "")
    if not st:
        st, d = services.match_place(state, district)
    else:
        d = next((x for x in places[st] if x.lower() == (district or "").strip().lower()), "")
        if not d:
            _, d = services.match_place(state, district)
    return st or (state or "").strip(), d or (district or "").strip()


def current(request) -> dict:
    loc = request.session.get("loc")
    if loc and (loc.get("state") or loc.get("district")):
        return loc
    u = request.user
    if u.is_authenticated and u.role == "farmer":
        fp = u.farmer_profile
        if fp.district:
            st, d = match(fp.state, fp.district)
            return {"state": st, "district": d, "src": "profile"}
    return {}


def label(loc: dict) -> str:
    return ", ".join(x for x in (loc.get("district"), loc.get("state")) if x)


def remember(request, state: str, district: str, src: str) -> dict:
    loc = {"state": state, "district": district, "src": src, "at": int(time.time())}
    request.session["loc"] = loc
    u = request.user
    if u.is_authenticated and u.role == "farmer":
        fp = u.farmer_profile
        if not fp.district and district:  # fill an empty profile, never overwrite what the farmer typed
            fp.state, fp.district = state or fp.state, district
            fp.save()
            audit.log("location_added_to_profile", actor=u, target=fp, request=request, via=src)
    return loc


def _throttled(request) -> bool:
    key = f"geo:{audit.client_ip(request) or 'x'}"
    cache.add(key, 0, 3600)
    try:
        return cache.incr(key) > MAX_LOOKUPS_PER_HOUR
    except ValueError:
        return False


@ensure_csrf_cookie
@require_POST
def resolve(request):
    """The browser's coordinates in, a district out. The coordinates are not stored; see rates.geocode for the ~1 km cache."""
    try:
        data = json.loads(request.body or b"{}")
        lat, lon = float(data["lat"]), float(data["lon"])
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    if _throttled(request):
        return JsonResponse({"ok": False, "error": "slow_down"}, status=429)
    try:
        state, district = geocode.reverse(lat, lon)
    except geocode.GeocodeError as e:
        return JsonResponse({"ok": False, "error": e.code})
    state, district = match(state, district)
    loc = remember(request, state, district, "gps")
    audit.log("location_shared", actor=request.user if request.user.is_authenticated else None, request=request, district=district, state=state)
    return JsonResponse({"ok": True, "state": loc["state"], "district": loc["district"], "label": label(loc)})


@require_POST
def choose(request):
    """A place picked by hand from the list of states and districts that have mandi data."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "bad_request"}, status=400)
    state, district = str(data.get("state", "")).strip(), str(data.get("district", "")).strip()
    places = known_places()
    if state not in places or (district and district not in places[state]):
        return JsonResponse({"ok": False, "error": "unknown_place"}, status=400)
    loc = remember(request, state, district, "manual")
    return JsonResponse({"ok": True, "state": loc["state"], "district": loc["district"], "label": label(loc)})
