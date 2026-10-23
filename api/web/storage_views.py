"""Warehouse receipts (e-NWR) and loans against them: plan, compare store-or-sell, record, get reminded."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import catalog
from accounts.errors import ApiError
from accounts.models import Role
from farmerbook.models import CropCycle
from market import stock
from rates import services as rate_services
from storage import services
from storage.models import Pledge, Warehouse

from .helpers import error_text, ok, warn
from .market_views import base_for


def _dec(v, default=None):
    try:
        return Decimal(str(v)) if v not in (None, "") else default
    except InvalidOperation:
        return default


def _date(v):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def hub(request):
    u = request.user
    if not u.is_authenticated:
        return render(request, "web/storage/about.html", {"base_tpl": "web/base.html"})
    if u.role != Role.FARMER:
        return render(request, "web/storage/about.html", {"base_tpl": base_for(u)})
    fp = u.farmer_profile
    lines = [ln for ln in stock.lines(u) if ln["free_kg"] > 0]
    pick = request.GET.get("line", "")
    chosen = None
    for ln in lines:
        ln["key"] = f"{ln['cycle'].pk}:{ln['product']}"
        if ln["key"] == pick:
            chosen = ln
    chosen = chosen or (lines[0] if lines else None)
    calc = None
    if chosen:
        ref = rate_services.typical_price(chosen["product"], fp.state, fp.district) if chosen["product"] in rate_services.CROPS else None
        price = _dec(request.GET.get("price"), ref["typical"] if ref else None)
        qty_q = _dec(request.GET.get("qty"), (chosen["free_kg"] / 100).quantize(Decimal("0.01")))
        months = int(_dec(request.GET.get("months"), Decimal(4)))
        rate_q = _dec(request.GET.get("storage"), Decimal("10"))
        ltv = _dec(request.GET.get("ltv"), services.DEFAULT_LTV)
        free_q = (chosen["free_kg"] / 100).quantize(Decimal("0.01"))
        capped = bool(qty_q and qty_q > free_q)
        qty_q = min(qty_q, free_q) if qty_q else qty_q
        if price and qty_q and qty_q > 0:
            calc = services.store_or_sell(qty_q * 100, price, max(1, min(months, 12)), rate_q, ltv)
            calc.update(price=price, qty_q=qty_q, months=months, storage_rate=rate_q, ltv=ltv, mandi=ref, capped=capped, free_q=free_q)
    near, rest = services.warehouses_near(fp.state, fp.district)
    return render(request, "web/storage/hub.html", {"lines": lines, "chosen": chosen, "calc": calc, "near": near, "rest": rest,
                                                    "pledges": Pledge.objects.filter(farmer=u).select_related("warehouse"), "base_tpl": base_for(u)})


@require_POST
def act(request, action):
    u = request.user
    if not u.is_authenticated or u.role != Role.FARMER:
        raise Http404
    P = request.POST
    try:
        if action == "plan":
            cid, _, product = (P.get("line") or "").partition(":")
            cycle = get_object_or_404(CropCycle, pk=cid, owner=u)
            wh = Warehouse.objects.filter(pk=P.get("warehouse")).first() if (P.get("warehouse") or "").isdigit() else None
            services.plan(u, cycle, product, (_dec(P.get("qty"), Decimal(0)) or Decimal(0)) * 100, wh, P.get("note", ""))
            ok(request, "Saved. Take the produce to the warehouse and write the e-NWR number here.")
        else:
            p = get_object_or_404(Pledge, pk=P.get("pledge"), farmer=u)
            if action == "deposit":
                services.record_deposit(p, P.get("enwr", ""), _date(P.get("deposit_date")) or date.today(), P.get("repository", ""), _date(P.get("valid_until")), _dec(P.get("value")))
            elif action == "loan":
                services.record_loan(p, P.get("bank", ""), _dec(P.get("amount")), _dec(P.get("rate")), _date(P.get("loan_date")) or date.today(), _date(P.get("due_date")))
            elif action == "close":
                services.close(p)
            else:
                raise Http404
            ok(request, "Saved.")
    except ApiError as e:
        warn(request, error_text(request, e))
    return redirect("/storage/")
