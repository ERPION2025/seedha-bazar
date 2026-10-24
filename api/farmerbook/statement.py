"""Income statement from the Farmer Book: what was grown, harvested, sold and spent in a period, stock on hand and debts.

Most figures are the farmer's own records. Some are confirmed by a second party and marked so: sales completed through
Seedha Bazar orders (the buyer confirmed delivery and payment) and sales made through the farmer's FPO group lot.
"""
import hashlib
import json
import secrets
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

import catalog

from .models import CropCycle, Expense, Harvest, Processing, Sale, Statement

D = Decimal


def _s(x) -> str:
    return str((x or D(0)).quantize(D("0.01")))


def build(user, start, end) -> dict:
    from market import stock
    from rates import services as rate_services

    fp = user.farmer_profile
    cycles = CropCycle.objects.filter(owner=user, deleted_at__isnull=True).select_related("plot")
    rows, tot_inc, tot_exp = [], D(0), D(0)
    for c in cycles:
        sales = Sale.objects.filter(crop_cycle=c, deleted_at__isnull=True, date__range=(start, end))
        exps = Expense.objects.filter(crop_cycle=c, deleted_at__isnull=True, date__range=(start, end))
        procs = Processing.objects.filter(crop_cycle=c, deleted_at__isnull=True, date__range=(start, end))
        harv = Harvest.objects.filter(crop_cycle=c, deleted_at__isnull=True, date__range=(start, end))
        inc = sales.aggregate(t=Sum("amount"))["t"] or D(0)
        exp = (exps.aggregate(t=Sum("amount"))["t"] or D(0)) + (procs.aggregate(t=Sum("cost"))["t"] or D(0))
        hkg = harv.aggregate(t=Sum("quantity_kg"))["t"] or D(0)
        if not (inc or exp or hkg):
            continue
        by_cat = defaultdict(D)
        for e in exps:
            by_cat[e.get_category_display()] += e.amount
        if procs.exists():
            by_cat["Processing"] += procs.aggregate(t=Sum("cost"))["t"] or D(0)
        verified = sales.filter(Q(channel="fpo", buyer_note__contains=" lot #")).aggregate(t=Sum("amount"))["t"] or D(0)
        area = c.plot.area_acres or D(0)
        rows.append({"crop": c.crop, "crop_name": catalog.name(c.crop), "season": c.get_season_display() if c.season else "", "plot": c.plot.name, "area_acres": _s(area),
                     "sown": c.sowing_date.isoformat() if c.sowing_date else "", "harvest_kg": _s(hkg), "per_acre_kg": _s(hkg / area) if area else "",
                     "sold_kg": _s(sales.aggregate(t=Sum("quantity_kg"))["t"]), "income": _s(inc), "expenses": _s(exp), "net": _s(inc - exp),
                     "expense_by": {k: _s(v) for k, v in sorted(by_cat.items())}, "verified_fpo": _s(verified)})
        tot_inc += inc
        tot_exp += exp
    general = Expense.objects.filter(owner=user, crop_cycle__isnull=True, deleted_at__isnull=True, date__range=(start, end)).aggregate(t=Sum("amount"))["t"] or D(0)
    tot_exp += general
    # Sales confirmed by buyers through Seedha Bazar orders
    from deals.models import Deal
    deals = Deal.objects.filter(seller=user, status="completed", completed_at__date__range=(start, end))
    deal_total = sum(((d.received_quantity or d.quantity) * d.price for d in deals), D(0))
    # Stock on hand, valued at today's price
    stock_rows, stock_value = [], D(0)
    for ln in stock.lines(user):
        kg = ln["in_book_kg"]
        if catalog.kind(ln["product"]) == catalog.SEMI:
            from catalog.services import reference_price
            rp = reference_price(ln["product"], fp.state)
            per_kg = rp["typical"] if rp else None
        else:
            ref = rate_services.typical_price(ln["product"], fp.state, fp.district) if ln["product"] in rate_services.CROPS else None
            per_kg = ref["typical"] / 100 if ref else None
        val = (kg * per_kg).quantize(D("1")) if per_kg else None
        stock_value += val or 0
        stock_rows.append({"product": catalog.name(ln["product"]), "kg": _s(kg), "value": _s(val) if val is not None else ""})
    from insurance.models import Application
    ins = [{"crop": catalog.name(a.crop), "season": a.get_season_display(), "year": a.year, "cover": _s(a.sum_insured), "policy": a.policy_no, "status": a.get_status_display()}
           for a in Application.objects.filter(farmer=user).exclude(status="closed")]
    from storage.models import Pledge
    debts = [{"what": f"Warehouse receipt loan ({catalog.name(p.product)})", "bank": p.bank, "amount": _s(p.loan_amount), "due": p.due_date.isoformat() if p.due_date else ""}
             for p in Pledge.objects.filter(farmer=user, status="loan")]
    org = fp.organisation if fp.org_status == "confirmed" else None
    return {
        "farmer": {"name": fp.name, "village": fp.village, "block": fp.block, "district": fp.district, "state": fp.state, "land_acres": _s(fp.land_acres),
                   "phone": user.phone, "level": fp.level, "fpo": org.name if org else "", "fpo_verified": bool(org and org.verified),
                   "land_record_verified": fp.land_record_verified, "documents_verified": fp.documents_verified},
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "crops": rows, "totals": {"income": _s(tot_inc), "expenses": _s(tot_exp), "net": _s(tot_inc - tot_exp), "general_expenses": _s(general),
                                  "per_acre_net": _s((tot_inc - tot_exp) / fp.land_acres) if fp.land_acres else ""},
        "confirmed": {"orders": _s(deal_total), "orders_count": deals.count(), "fpo_lots": _s(sum((D(r["verified_fpo"]) for r in rows), D(0)))},
        "stock": stock_rows, "stock_value": _s(stock_value), "insurance": ins, "debts": debts,
        "generated": timezone.now().isoformat(timespec="seconds"),
    }


def digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def make(user, start, end, made_by=None) -> Statement:
    if end < start:
        start, end = end, start
    data = build(user, start, end)
    return Statement.objects.create(owner=user, made_by=made_by or user, code=secrets.token_urlsafe(8)[:10].replace("-", "x").replace("_", "y"),
                                    period_from=start, period_to=end, data=data, digest=digest(data))


def default_period(today=None):
    today = today or timezone.localdate()
    return today - timedelta(days=365), today
