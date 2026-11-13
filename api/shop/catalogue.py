"""What the storefront shows about each product, the way people expect from big online shops: star rating and number of
ratings, how many bought it lately, price against MRP with the discount, a delivery date for the buyer's PIN code,
free delivery, stock left, where it comes from and who made it. Plus the filters and sorting for the listing pages."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db.models import Avg, Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import shipping
from .models import CATEGORIES, OrderLine, Product, SellerSettings

CAT = {k: (label, emoji) for k, label, emoji in CATEGORIES}
SORTS = [("relevance", "Relevance"), ("popular", "Most bought"), ("rating", "Top rated"), ("price_low", "Price: low to high"),
         ("price_high", "Price: high to low"), ("new", "Newest first")]
PRICE_BANDS = [(0, 250), (250, 500), (500, 1000), (1000, 2500), (2500, None)]


def base_qs():
    since = timezone.now() - timedelta(days=30)
    sold = (OrderLine.objects.filter(product=OuterRef("pk"), order__created_at__gte=since).exclude(order__status="cancelled").values("product")
            .annotate(n=Sum("quantity")).values("n"))
    return (Product.objects.filter(status=Product.Status.LIVE, stock__gt=0).select_related("organisation", "seller__farmer_profile")
            .annotate(rating=Avg("reviews__stars", filter=Q(reviews__hidden=False)), ratings_n=Count("reviews", filter=Q(reviews__hidden=False), distinct=True),
                      sold_30=Coalesce(Subquery(sold, output_field=IntegerField()), Value(0))))


def filtered(params: dict):
    """The listing for these filters and this sort. Prices are filtered on what the buyer pays."""
    qs = base_qs()
    q = (params.get("q") or "").strip()[:60]
    if q:
        for word in q.split()[:5]:
            qs = qs.filter(Q(title__icontains=word) | Q(description__icontains=word) | Q(highlights__icontains=word) | Q(village__icontains=word)
                           | Q(district__icontains=word) | Q(organisation__name__icontains=word))
    if params.get("cat") in CAT:
        qs = qs.filter(category=params["cat"])
    if params.get("from") in ("warehouse", "seller"):
        qs = qs.filter(fulfilment=params["from"])
    if params.get("state"):
        qs = qs.filter(state__iexact=params["state"])
    if params.get("seller", "").isdigit():
        qs = qs.filter(seller_id=int(params["seller"]))
    if params.get("rating") in ("3", "4"):
        qs = qs.filter(rating__gte=int(params["rating"]))
    band = params.get("price", "")
    if "-" in band:
        lo, _, hi = band.partition("-")
        # buyer price = price x (1 + fee); filter roughly on the reviewed price, then exactly in Python
        qs = qs.filter(price__gte=Decimal(lo or 0) / Decimal("1.3"))
        if hi:
            qs = qs.filter(price__lte=Decimal(hi))
    order = {"popular": ("-sold_30", "-ratings_n"), "rating": ("-rating", "-ratings_n"), "price_low": ("price",), "price_high": ("-price",),
             "new": ("-reviewed_at",)}.get(params.get("sort", ""), ("-sold_30", "-rating", "-reviewed_at"))
    return qs.order_by(*[o if o.lstrip("-") != "rating" else o for o in order])


def facets(params: dict) -> dict:
    """Counts beside each filter, for the listing as filtered by everything else."""
    def without(key):
        return filtered({k: v for k, v in params.items() if k != key})
    cats = dict(without("cat").values_list("category").annotate(n=Count("id")))
    states = without("state").exclude(state="").values("state").annotate(n=Count("id")).order_by("-n")[:12]
    ships = dict(without("from").values_list("fulfilment").annotate(n=Count("id")))
    return {"cats": [(k, label, emoji, cats.get(k, 0)) for k, label, emoji in CATEGORIES if cats.get(k)], "states": list(states), "ships": ships,
            "bands": [(f"{lo}-{hi or ''}", lo, hi) for lo, hi in PRICE_BANDS]}


def _deliver_by(days: str):
    upper = int(days.split("-")[-1])
    d = timezone.localdate() + timedelta(days=upper)
    if d.weekday() == 6:  # couriers rest on Sunday
        d += timedelta(days=1)
    return d


def decorate(rows, pin: str = "", user=None) -> list:
    """Add everything a product card shows."""
    from .services import buyer_price, fees

    rows = list(rows)
    seller_pins = dict(SellerSettings.objects.filter(user_id__in={p.seller_id for p in rows}).values_list("user_id", "pincode"))
    top = {}
    for p in rows:  # the best seller in each category on this page gets the badge
        if p.sold_30 and p.sold_30 > top.get(p.category, (0, None))[0]:
            top[p.category] = (p.sold_30, p.pk)
    for p in rows:
        p.show_price = buyer_price(p)
        _, bp = fees(p.category)
        p.show_mrp = (p.mrp * (1 + bp / 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP) if p.mrp and p.mrp > p.price else None
        p.off = int(round((1 - p.show_price / p.show_mrp) * 100)) if p.show_mrp else 0
        p.stars = round(float(p.rating or 0) * 2) / 2
        p.stars_full = int(p.stars)
        p.stars_half = p.stars - p.stars_full >= 0.5
        p.cat_label, p.cat_emoji = CAT.get(p.category, ("", "🛍️"))
        p.place = place_of(p.village, p.district, p.state) or p.origin
        p.from_warehouse = p.fulfilment == "warehouse"
        p.maker = p.organisation.name if p.organisation_id else ((getattr(p.seller, "farmer_profile", None) and p.seller.farmer_profile.name) or "")
        p.bestseller = top.get(p.category, (0, None))[1] == p.pk and p.sold_30 >= 3
        p.sold_label = "" if p.sold_30 < 5 else (f"{(p.sold_30 // 10) * 10}+" if p.sold_30 >= 10 else f"{p.sold_30}+")
        p.free_delivery = p.show_price >= settings.SHOP_FREE_DELIVERY_ABOVE
        p.low_stock = p.stock <= 5
        origin_pin = settings.SHOP_WAREHOUSE["pincode"] if p.from_warehouse else seller_pins.get(p.seller_id, "")
        p.deliver_by = _deliver_by(shipping.quote(origin_pin, pin, p.weight_g)["days"]) if pin and origin_pin else None
    return rows


def place_of(*parts) -> str:
    """Village, district, state, without saying the same name twice (Mandla village in Mandla district)."""
    out = []
    for x in parts:
        if x and x.strip().lower() not in [o.lower() for o in out]:
            out.append(x.strip())
    return ", ".join(out)


def lines_of(text: str) -> list:
    return [x.strip(" •-\t") for x in (text or "").splitlines() if x.strip(" •-\t")]


def specs(p) -> list:
    """The specifications table: what the maker wrote, then what Seedha Bazar knows."""
    rows = []
    for line in lines_of(p.details):
        name, sep, value = line.partition(":")
        if sep and name.strip() and value.strip():
            rows.append((name.strip()[:40], value.strip()[:120]))
    rows += [("Category", CAT.get(p.category, ("",))[0]), ("Pack", p.pack), ("Packed weight", f"{p.weight_g} g"),
             ("Made in", place_of(p.village, p.district, p.state))]
    if p.hsn:
        rows.append(("HSN code", p.hsn))
    if p.fssai_no:
        rows.append(("FSSAI licence", p.fssai_no))
    if p.shelf_life_days:
        rows.append(("Shelf life", f"{p.shelf_life_days} days"))
    return rows


def rating_summary(p) -> dict:
    qs = p.reviews.filter(hidden=False)
    n = qs.count()
    dist = dict(qs.values_list("stars").annotate(c=Count("id")))
    avg = qs.aggregate(a=Avg("stars"))["a"] or 0
    return {"n": n, "avg": round(avg, 1), "bars": [(s, dist.get(s, 0), int(round(dist.get(s, 0) * 100 / n)) if n else 0) for s in (5, 4, 3, 2, 1)]}
