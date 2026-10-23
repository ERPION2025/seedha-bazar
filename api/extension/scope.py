"""District scope (the geofence) and the numbers that describe a district.

Aggregates (counts, totals, averages) cover everyone in the district and name no one. Individual farmer details are shown
to a centre only when that farmer has said yes to sharing with their district's extension centre.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from accounts.models import Role, UserStatus
from farmerbook.models import CropCycle, Harvest, Processing, Sale
from profiles.models import FarmerProfile, Organisation, OrgStatus

from .models import Centre, CentreMember

D = Decimal
MIN_GROUP = 3  # an average is shown only when at least this many farmers are in it, so no one can be singled out


def centres_of(user):
    return Centre.objects.filter(members__user=user).distinct()


def centre_for_place(state: str, district: str) -> Centre | None:
    """The centre whose geofence holds this district: a KVK first, then any other centre."""
    if not district:
        return None
    rows = [c for c in Centre.objects.filter(verified=True) if c.covers(state, district)]
    rows.sort(key=lambda c: c.kind != Centre.Kind.KVK)
    return rows[0] if rows else None


def _district_q(prefix: str, state: str, districts) -> Q:
    """Rows in these districts. Names are matched loosely ("Khandwa" also finds "Khandwa (East Nimar)")."""
    q = Q()
    for d in districts:
        base = d.split("(")[0].strip()
        q |= Q(**{f"{prefix}district__iexact": d}) | Q(**{f"{prefix}district__istartswith": base})
    if state:
        q &= Q(**{f"{prefix}state__iexact": state})
    return q


def farmers(centre: Centre, district: str = ""):
    ds = [district] if district else centre.districts
    return FarmerProfile.objects.filter(_district_q("", centre.state, ds), user__status__in=[UserStatus.ACTIVE, UserStatus.PENDING]).select_related("user", "organisation")


def orgs(centre: Centre, district: str = ""):
    ds = [district] if district else centre.districts
    return Organisation.objects.filter(_district_q("", centre.state, ds))


def yields(state: str, districts, crop: str = "") -> list[dict]:
    """Harvest per acre by crop, from Farmer Books. Each row: crop, farmers, average, best, median (kg per acre)."""
    per: dict = defaultdict(list)
    cycles = CropCycle.objects.filter(deleted_at__isnull=True, owner__farmer_profile__in=FarmerProfile.objects.filter(_district_q("", state, districts))).select_related("plot", "owner")
    if crop:
        cycles = cycles.filter(crop=crop)
    sums = {r["crop_cycle"]: r["kg"] for r in Harvest.objects.filter(deleted_at__isnull=True, crop_cycle__in=cycles).values("crop_cycle").annotate(kg=Sum("quantity_kg"))}
    for c in cycles:
        kg = sums.get(c.pk)
        if kg and c.plot.area_acres and c.plot.area_acres > 0:
            per[c.crop].append((kg / c.plot.area_acres, c.owner_id))
    out = []
    for crop_key, rows in per.items():
        farmers_n = len({o for _, o in rows})
        vals = sorted(v for v, _ in rows)
        out.append({"crop": crop_key, "farmers": farmers_n, "average": (sum(vals) / len(vals)).quantize(D("1")), "median": vals[len(vals) // 2].quantize(D("1")),
                    "best": vals[-1].quantize(D("1")), "enough": farmers_n >= MIN_GROUP, "values": rows})
    out.sort(key=lambda r: -r["farmers"])
    return out


def percentile(value: Decimal, values: list) -> int:
    if not values:
        return 0
    below = sum(1 for v in values if v < value)
    return int(round(below * 100 / len(values)))


def district_picture(centre: Centre, district: str = "") -> dict:
    """Everything the control centre shows for its districts (or one of them)."""
    from catalog.services import odop_for
    from deals.models import Deal
    from insurance.models import Application
    from market import stock
    from market.models import Listing
    from rates import services as rate_services

    ds = [district] if district else centre.districts
    now = timezone.now()
    since = now - timedelta(days=90)
    fps = farmers(centre, district)
    users = [fp.user for fp in fps[:3000]]
    crop_counts: dict = defaultdict(int)
    land = D(0)
    for fp in fps:
        land += fp.land_acres or 0
        for c in fp.crops or []:
            crop_counts[c] += 1
    area = defaultdict(D)
    for c in CropCycle.objects.filter(owner__in=users, deleted_at__isnull=True, status="active").select_related("plot"):
        area[c.crop] += c.plot.area_acres or 0
    stock_by = defaultdict(D)
    for ln in stock.lines(users) if users else []:
        stock_by[ln["product"]] += ln["in_book_kg"]
    sales = Sale.objects.filter(owner__in=users, deleted_at__isnull=True, date__gte=since.date())
    sales_by = defaultdict(lambda: {"kg": D(0), "amount": D(0)})
    for s in sales.values("crop_cycle__crop", "product").annotate(kg=Sum("quantity_kg"), amount=Sum("amount")):
        key = s["product"] or s["crop_cycle__crop"]
        sales_by[key]["kg"] += s["kg"] or 0
        sales_by[key]["amount"] += s["amount"] or 0
    deals = Deal.objects.filter(Q(seller__in=users) | Q(organisation__in=orgs(centre, district)))
    listings = Listing.live().filter(_district_q("", centre.state, ds))
    ins = Application.objects.filter(_district_q("", centre.state, ds))
    from issues.models import Issue
    issues = Issue.objects.filter(_district_q("", centre.state, ds))
    top_crops = sorted(crop_counts, key=lambda c: -crop_counts[c])[:6]
    rates = []
    for c in top_crops:
        q = rate_services.quote(c, centre.state, ds[0] if ds else "") if c in rate_services.CROPS else None
        if q and q.get("typical"):
            rates.append({"crop": c, "typical": q["typical"], "trend": q.get("trend"), "as_of": q.get("as_of")})
    return {
        "districts": ds,
        "farmers": fps.count(), "farmers_new": fps.filter(user__date_joined__gte=now - timedelta(days=30)).count(),
        "sharing": fps.filter(share_with_extension=True).count(),
        "orgs": orgs(centre, district).filter(verified=True).count(), "fpos": orgs(centre, district).filter(verified=True, kind="fpo").count(),
        "ngos": orgs(centre, district).filter(verified=True, kind="ngo").count(),
        "land": land.quantize(D("0.1")), "crops": [{"crop": c, "farmers": crop_counts[c], "area": area.get(c, D(0))} for c in sorted(crop_counts, key=lambda c: -crop_counts[c])[:12]],
        "stock": sorted(({"product": k, "kg": v} for k, v in stock_by.items() if v > 0), key=lambda r: -r["kg"])[:12],
        "stock_total": sum(stock_by.values(), D(0)),
        "sales": sorted(({"product": k, **v} for k, v in sales_by.items()), key=lambda r: -r["amount"])[:10],
        "sales_total": sum((v["amount"] for v in sales_by.values()), D(0)),
        "listings": listings.count(), "listings_value": sum((li.total_value for li in listings[:500]), D(0)),
        "deals_open": deals.filter(status__in=Deal.OPEN).count(), "deals_done": deals.filter(status="completed").count(),
        "insured": ins.exclude(status="closed").count(), "insured_cover": ins.exclude(status="closed").aggregate(t=Sum("sum_insured"))["t"] or 0,
        "losses": ins.filter(status="loss").count(),
        "issues_open": issues.filter(status__in=["open", "acknowledged"]).count(),
        "issues_overdue": issues.filter(status="open", created_at__lt=now - timedelta(hours=48)).count(),
        "issues_resolved": issues.filter(status="resolved", updated_at__gte=now - timedelta(days=30)).count(),
        "issue_kinds": [{**r, "label": dict(Issue.Category.choices).get(r["category"], r["category"])}
                        for r in issues.filter(created_at__gte=since).values("category").annotate(n=Count("id")).order_by("-n")[:8]],
        "yields": [y for y in yields(centre.state, ds) if y["enough"]][:10],
        "rates": rates, "odop": [odop_for(centre.state, d) for d in ds],
    }
