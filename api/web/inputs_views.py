"""Seeds, fertilisers and other inputs that the district's KVK or research centre offers, and requests for them."""
from decimal import Decimal, InvalidOperation

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.errors import ApiError
from accounts.models import Role
from extension import geo
from extension import services as ext
from extension.models import Centre, InputOffer, InputRequest
from extension.scope import centre_for_place
from profiles.models import Organisation

from .helpers import error_text, ok, warn
from .market_views import base_for


def offers(request):
    u = request.user
    if not u.is_authenticated or u.role not in (Role.FARMER, Role.AGENT):
        return redirect("/login/?next=/inputs/")
    rows = ext.offers_for(u)
    mine = InputRequest.objects.filter(user=u).select_related("offer__centre")[:30]
    asked = {r.offer_id for r in mine if r.status in ("requested", "approved")}
    return render(request, "web/inputs/list.html", {"rows": rows, "mine": mine, "asked": asked, "base_tpl": base_for(u)})


@require_POST
def ask(request, pk):
    u = request.user
    if not u.is_authenticated:
        raise Http404
    o = get_object_or_404(InputOffer, pk=pk)
    try:
        qty = Decimal(request.POST.get("quantity", ""))
    except InvalidOperation:
        qty = None
    try:
        ext.request(o, u, qty, request.POST.get("note", ""), request)
        ok(request, "Request sent to {centre}.", centre=o.centre.name)
    except ApiError as e:
        warn(request, error_text(request, e))
    return redirect("/inputs/")


def map_page(request):
    """Nearby KVKs and research centres, verified FPOs and NGOs, and your district's outline."""
    from extension.services import place_of
    state, district = "", ""
    if request.user.is_authenticated:
        state, district, _ = place_of(request.user)
    if not state:
        from . import location
        loc = location.current(request)
        state, district = loc.get("state", ""), loc.get("district", "")
    from django.conf import settings
    state = state or settings.DEFAULT_STATE
    return render(request, "web/map.html", {"state": state, "district": geo.official_name(state, district) if district else "", "state_file": geo.state_file(state),
                                            "centre": centre_for_place(state, district), "base_tpl": base_for(request.user) if request.user.is_authenticated else "web/base.html"})


def map_data(request):
    """Public points only: centres and verified FPOs/NGOs with an office location. Never farmers."""
    state = request.GET.get("state", "")
    cs = Centre.objects.filter(verified=True, lat__isnull=False)
    os_ = Organisation.objects.filter(verified=True, lat__isnull=False)
    if state:
        cs, os_ = cs.filter(state__iexact=state), os_.filter(state__iexact=state)
    return JsonResponse({
        "centres": [{"name": c.name, "kind": c.get_kind_display(), "lat": c.lat, "lon": c.lon, "phone": c.phone, "address": c.address, "districts": c.districts} for c in cs[:300]],
        "orgs": [{"name": o.name, "kind": o.get_kind_display(), "lat": o.lat, "lon": o.lon, "district": o.district} for o in os_[:500]],
    })


@require_POST
def set_org_location(request):
    """An FPO agent saves the office location from their phone, so buyers and the KVK can find it on the map."""
    u = request.user
    if not u.is_authenticated or u.role != Role.AGENT:
        raise Http404
    from profiles.models import OrgMembership
    m = OrgMembership.objects.filter(user=u).select_related("organisation").first()
    if m is None:
        raise Http404
    try:
        lat, lon = float(request.POST["lat"]), float(request.POST["lon"])
    except (KeyError, ValueError):
        warn(request, "Something went wrong. Please try again.")
        return redirect("/fpo/")
    where = geo.district_at(lat, lon)
    if where is None:
        warn(request, "That location is outside India.")
        return redirect("/fpo/")
    org = m.organisation
    org.lat, org.lon = round(lat, 5), round(lon, 5)
    org.save(update_fields=["lat", "lon"])
    ok(request, "Office location saved: {place}.", place=f"{where[1]}, {where[0]}")
    return redirect("/fpo/")


@require_POST
def consent(request):
    """A farmer's yes or no to sharing their profile and book with the district's KVK or research centre."""
    u = request.user
    if not u.is_authenticated or u.role != Role.FARMER:
        raise Http404
    fp = u.farmer_profile
    fp.share_with_extension = request.POST.get("share") == "1"
    fp.save()
    from accounts import audit
    audit.log("extension_sharing_set", actor=u, target=fp, request=request, share=fp.share_with_extension)
    ok(request, "Saved.")
    return redirect(request.POST.get("back") if (request.POST.get("back") or "").startswith("/farmer/") else "/farmer/")
