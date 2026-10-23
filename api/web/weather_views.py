"""Village weather with advice for each crop, from its stage in the Farmer Book."""
from django.shortcuts import render
from django.utils import timezone

from accounts.models import Role
from weather import services, stages
from weather.models import Alert

from . import location
from .market_views import base_for

ICONS = {0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌦️", 55: "🌧️", 61: "🌦️", 63: "🌧️", 65: "🌧️", 80: "🌦️", 81: "🌧️", 82: "⛈️", 95: "⛈️", 96: "⛈️", 99: "⛈️"}


def page(request):
    u = request.user
    state = district = village = ""
    org = None
    if u.is_authenticated:
        from extension.services import place_of
        state, district, org = place_of(u)
        if u.role == Role.FARMER:
            village = u.farmer_profile.village
        elif org is not None:
            village = org.block
    if not district:
        loc = location.current(request)
        state, district = loc.get("state", ""), loc.get("district", "")
    place = services.place_for(state, district, village) if district else None
    days = services.forecast(place.lat, place.lon) if place else None
    for d in days or []:
        d["icon"] = ICONS.get(d.get("code"), "🌡️")
    crops, alerts = [], []
    if u.is_authenticated and u.role == Role.FARMER and days:
        crops = services.crop_rows(u)
        alerts = services.alerts_for(u, days)
    members_alerts = []
    if u.is_authenticated and u.role == Role.AGENT and org is not None:
        members_alerts = Alert.objects.filter(farmer__farmer_profile__organisation=org, day__gte=timezone.localdate()).select_related("farmer__farmer_profile")[:50]
    return render(request, "web/weather.html", {"place": place, "days": days, "crops": crops, "alerts": alerts, "members_alerts": members_alerts, "district": district,
                                                "village": village, "base_tpl": base_for(u) if u.is_authenticated else "web/base.html"})


def home_alert(user):
    """The most urgent advice for the home page, from the cached forecast only (no waiting on the network)."""
    fp = user.farmer_profile
    if not fp.district:
        return None
    place = services.place_for(fp.state, fp.district, fp.village, lookup=False)
    days = services.forecast(place.lat, place.lon, fetch=False) if place else None
    if not days:
        return None
    rows = services.alerts_for(user, days)
    order = ["frost", "rain", "wind", "heat", "disease", "dry"]
    rows.sort(key=lambda a: (a["day"], order.index(a["kind"])))
    return {"alert": rows[0] if rows else None, "today": days[0] | {"icon": ICONS.get(days[0].get("code"), "🌡️")}}
