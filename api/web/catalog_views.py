"""Pages that show what each crop can become and what it is worth: "Earn more from your produce"."""
from decimal import Decimal, InvalidOperation

from django.http import Http404
from django.shortcuts import render

import catalog
from catalog import services as cat
from rates import services as rate_services

from . import location
from .market_views import base_for


def _place(request):
    u = request.user
    fp = getattr(u, "farmer_profile", None) if u.is_authenticated and u.role == "farmer" else None
    if fp and fp.district:
        return fp.state, fp.district
    loc = location.current(request)
    return loc.get("state", ""), loc.get("district", "")


def index(request):
    state, district = _place(request)
    rows = []
    for key in catalog.keys_of(catalog.RAW, catalog.FRESH):
        n = len(cat.conversions_from(key))
        if n:
            rows.append({"crop": key, "emoji": catalog.emoji(key), "n": n, "fresh": catalog.kind(key) == catalog.FRESH})
    odop = cat.featured_for(state, district)
    return render(request, "web/value/index.html", {"rows": rows, "featured": odop, "base_tpl": base_for(request.user) if request.user.is_authenticated else "web/base.html"})


def crop_page(request, crop):
    if crop not in catalog.PRODUCTS or catalog.kind(crop) == catalog.SEMI:
        raise Http404
    state, district = _place(request)
    try:
        qty = Decimal(request.GET.get("qty", "") or "0")
    except InvalidOperation:
        qty = Decimal(0)
    qty = qty if Decimal(0) < qty <= Decimal("100000") else Decimal(0)  # quintal of the raw crop
    options = cat.value_options(crop, state, district, request.lang)
    for o in options:
        o["needs"] = o["needs"]
        if qty:
            f = qty / 1  # per 100 kg figures are per 0.01 quintal... scale: quintal * 1
            o["total_revenue"] = (o["revenue"] * f).quantize(Decimal("1"))
            o["total_cost"] = (o["cost"] * f).quantize(Decimal("1"))
            o["total_gain"] = (o["gain"] * f).quantize(Decimal("1")) if o["gain"] is not None else None
            o["total_kg"] = (o["kg_out"] * f).quantize(Decimal("0.1"))
    quote = rate_services.quote(crop, state, district) if crop in rate_services.CROPS else None
    ctx = {"crop": crop, "emoji": catalog.emoji(crop), "options": options, "quote": quote, "qty": qty, "state": state, "district": district,
           "fresh": catalog.kind(crop) == catalog.FRESH, "base_tpl": base_for(request.user) if request.user.is_authenticated else "web/base.html",
           "can_record": request.user.is_authenticated and request.user.role == "farmer"}
    return render(request, "web/value/crop.html", ctx)
