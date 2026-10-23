"""Two numbers each farmer can understand and improve.

Activity (0-100, last 30 days): how much they use Seedha Bazar: days active, Farmer Book entries, selling, learning, profile.
Performance (0-100): how well the farm does: harvest per acre against the district, profit, sale price against the mandi,
completed orders and their ratings, and whether crops are insured. Each part says how it was worked out.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

D = Decimal


def _cap(x, top):
    return max(0, min(top, int(round(x))))


def activity(user, now=None) -> dict:
    from accounts.models import AuditEvent
    from farmerbook.models import Activity, Expense, Harvest, Processing, Sale
    from market.models import Listing

    from .models import GamePlay

    now = now or timezone.now()
    since = now - timedelta(days=30)
    days = AuditEvent.objects.filter(actor=user, created_at__gte=since).annotate(d=TruncDate("created_at")).values("d").distinct().count()
    book = sum(m.objects.filter(owner=user, created_at__gte=since, deleted_at__isnull=True).count() for m in (Expense, Harvest, Sale, Activity, Processing))
    selling = Listing.objects.filter(seller=user, updated_at__gte=since).count()
    from deals.models import Deal
    selling += Deal.objects.filter(Q(seller=user) | Q(buyer=user), updated_at__gte=since).count()
    games = GamePlay.objects.filter(user=user, played_at__gte=since).count()
    from issues.models import Issue
    asked = Issue.objects.filter(raised_by=user, created_at__gte=since).count()
    level = getattr(getattr(user, "farmer_profile", None), "level", 0)
    parts = [
        ("Days you used the app", _cap(days, 30), 30, f"{days}"),
        ("Farmer Book entries", _cap(book, 25), 25, f"{book}"),
        ("Selling: listings and orders", _cap(selling * 3, 15), 15, f"{selling}"),
        ("Learning: games and expert questions", _cap(games + asked * 2, 15), 15, f"{games + asked}"),
        ("Profile level", level * 5, 15, f"{level}/3"),
    ]
    return {"score": sum(p[1] for p in parts), "parts": [{"label": p[0], "got": p[1], "of": p[2], "count": p[3]} for p in parts]}


def performance(user) -> dict:
    from extension.scope import percentile, yields
    from farmerbook.models import CropCycle, Sale
    from farmerbook.views import ledger_for
    from rates import services as rate_services

    fp = getattr(user, "farmer_profile", None)
    parts = []
    # 1. Harvest per acre against the district (40)
    pcts = []
    if fp and fp.district:
        ys = {y["crop"]: y for y in yields(fp.state, [fp.district]) if y["enough"]}
        from farmerbook.views import cycle_summary
        for c in CropCycle.objects.filter(owner=user, deleted_at__isnull=True).select_related("plot"):
            y = ys.get(c.crop)
            s = cycle_summary(c)
            if y and c.plot.area_acres and D(s["harvested_kg"]) > 0:
                pcts.append(percentile(D(s["harvested_kg"]) / c.plot.area_acres, [v for v, _ in y["values"]]))
    parts.append(("Harvest per acre against your district", _cap(sum(pcts) / len(pcts) * 0.4, 40) if pcts else 0, 40,
                  f"{int(sum(pcts) / len(pcts))}%" if pcts else "—"))
    # 2. Profit (20): revenue against costs
    led = ledger_for(user)["totals"]
    exp, rev = D(led["expenses"]), D(led["revenue"])
    ratio = (rev / exp) if exp > 0 else (D(2) if rev > 0 else D(0))
    parts.append(("Money earned against money spent", _cap(min(ratio, D(2)) * 10, 20), 20, f"{ratio:.1f}x" if exp > 0 or rev > 0 else "—"))
    # 3. Sale price against the mandi (20)
    gaps = []
    for s in Sale.objects.filter(owner=user, deleted_at__isnull=True, product="").select_related("crop_cycle")[:50]:
        ref = rate_services.typical_price(s.crop_cycle.crop, fp.state if fp else "", fp.district if fp else "") if s.crop_cycle.crop in rate_services.CROPS else None
        if ref and s.quantity_kg:
            per_q = s.amount / s.quantity_kg * 100
            gaps.append(float(per_q / ref["typical"]))
    avg_gap = sum(gaps) / len(gaps) if gaps else None
    parts.append(("Your sale price against the mandi", _cap((avg_gap - 0.8) / 0.4 * 20, 20) if avg_gap else 0, 20, f"{avg_gap * 100:.0f}%" if avg_gap else "—"))
    # 4. Orders completed and ratings (10)
    from deals.models import Deal
    done = Deal.objects.filter(seller=user, status="completed")
    rating = done.aggregate(a=Avg("buyer_rating"))["a"]
    parts.append(("Orders completed and buyer ratings", _cap(min(done.count(), 5) + (rating or 0), 10), 10, f"{done.count()}" + (f" · {rating:.1f}★" if rating else "")))
    # 5. Crops insured (10)
    from insurance.models import Application
    active = CropCycle.objects.filter(owner=user, deleted_at__isnull=True, status="active").count()
    insured = Application.objects.filter(farmer=user).exclude(status="closed").count()
    parts.append(("Crops insured", _cap(min(insured, active) / active * 10, 10) if active else 0, 10, f"{min(insured, active)}/{active}" if active else "—"))
    return {"score": sum(p[1] for p in parts), "parts": [{"label": p[0], "got": p[1], "of": p[2], "count": p[3]} for p in parts]}


def district_insights(state: str, district: str) -> dict:
    """What a district grows, harvests and earns, from Farmer Books and the market. Averages only where 3 or more farmers are in it."""
    from extension.scope import MIN_GROUP, yields
    from farmerbook.models import Sale
    from profiles.models import FarmerProfile
    from rates import services as rate_services

    fps = FarmerProfile.objects.filter(state__iexact=state, district__iexact=district)
    crops: dict = {}
    for fp in fps:
        for c in fp.crops or []:
            crops[c] = crops.get(c, 0) + 1
    prices = []
    rows = Sale.objects.filter(owner__farmer_profile__in=fps, deleted_at__isnull=True, product="", date__gte=timezone.localdate() - timedelta(days=180)).values("crop_cycle__crop").annotate(
        kg=Sum("quantity_kg"), amount=Sum("amount"), n=Count("owner", distinct=True))
    for r in rows:
        if r["n"] >= MIN_GROUP and r["kg"]:
            crop = r["crop_cycle__crop"]
            ref = rate_services.typical_price(crop, state, district) if crop in rate_services.CROPS else None
            prices.append({"crop": crop, "farmers": r["n"], "avg": (r["amount"] / r["kg"] * 100).quantize(D("1")), "mandi": ref["typical"] if ref else None})
    return {"farmers": fps.count(), "crops": sorted(crops.items(), key=lambda kv: -kv[1])[:10], "yields": [y for y in yields(state, [district]) if y["enough"]],
            "prices": prices}
