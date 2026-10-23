"""What the catalog knows, put to work: what a raw product can become, what the result is worth, what a place is known for."""
from decimal import Decimal
from statistics import median

from django.utils import timezone

from rates import services as rate_services

from . import PRODUCTS
from .data import CONVERSIONS, NEEDS
from .models import DistrictProduct

D = Decimal
LANG_INDEX = {"en": 0, "hi": 1, "mr": 2}


def _mid(pair) -> Decimal:
    return (D(str(pair[0])) + D(str(pair[1]))) / 2


def conversions_from(crop: str) -> list[tuple]:
    return [c for c in CONVERSIONS if c[0] == crop]


def conversions_to(product: str) -> list[tuple]:
    return [c for c in CONVERSIONS if c[1] == product]


def how_text(conv: tuple, lang: str) -> str:
    return conv[6][LANG_INDEX.get(lang, 1)]


def needs_for(conv: tuple) -> list[str]:
    """English names of what the work needs (translated by the caller)."""
    return [NEEDS[n][0] for n in conv[5]]


def reference_price(product: str, state: str = "") -> dict | None:
    """What a processed product sells for per kg: the platform's own live listings when there are enough, else the catalog's starter range.

    Returns {"low", "high", "typical", "source": "listings"|"estimate", "n"}; None when there is nothing to say.
    """
    from market.models import Listing

    qs = Listing.live().filter(crop=product)
    if state:
        scoped = qs.filter(state__iexact=state)
        qs = scoped if scoped.count() >= 2 else qs
    prices = sorted(p / 100 for p in qs.values_list("price_per_quintal", flat=True)[:200])
    if len(prices) >= 2:
        return {"low": prices[0], "high": prices[-1], "typical": D(str(median(prices))).quantize(D("1")), "source": "listings", "n": len(prices)}
    ranges = [c[4] for c in conversions_to(product)]
    if not ranges:
        return None
    lo, hi = min(r[0] for r in ranges), max(r[1] for r in ranges)
    return {"low": D(lo), "high": D(hi), "typical": _mid((lo, hi)).quantize(D("1")), "source": "estimate", "n": 0}


def value_options(crop: str, state: str = "", district: str = "", lang: str = "en") -> list[dict]:
    """For 100 kg of `crop`: each thing it could be turned into, with the money worked out against today's mandi price.

    `gain` is revenue minus processing cost minus what the raw 100 kg would sell for. It is None when we have no mandi price.
    All prices for processed goods are estimates (see reference_price) and are labelled so.
    """
    ref = rate_services.typical_price(crop, state, district) if crop in PRODUCTS else None
    raw_kg = (ref["typical"] / 100) if ref else None
    out = []
    for conv in conversions_from(crop):
        _, to, yld, cost, price, needs, _how = conv
        rp = reference_price(to, state) or {"low": D(price[0]), "high": D(price[1]), "typical": _mid(price), "source": "estimate", "n": 0}
        kg_out = _mid(yld)  # per 100 kg in
        revenue = kg_out * rp["typical"]
        raw_value = raw_kg * 100 if raw_kg else None
        gain = revenue - D(str(cost)) * 100 - raw_value if raw_value is not None else None
        out.append({
            "to": to, "name": PRODUCTS[to][0], "emoji": PRODUCTS[to][3], "yield_low": yld[0], "yield_high": yld[1], "kg_out": kg_out.quantize(D("0.1")),
            "price": rp, "revenue": revenue.quantize(D("1")), "cost": (D(str(cost)) * 100).quantize(D("1")), "raw_value": raw_value.quantize(D("1")) if raw_value is not None else None,
            "gain": gain.quantize(D("1")) if gain is not None else None, "multiple": (revenue / raw_value).quantize(D("0.1")) if raw_value else None,
            "needs": needs_for(conv), "how": how_text(conv, lang), "fssai": "fssai" in needs, "mandi": ref,
        })
    out.sort(key=lambda o: (o["gain"] is None, -(o["gain"] or 0), o["name"]))
    return out


def odop_for(state: str, district: str) -> DistrictProduct | None:
    if not district:
        return None
    qs = DistrictProduct.objects.filter(district__iexact=district.strip())
    if state:
        scoped = qs.filter(state__iexact=state.strip())
        qs = scoped if scoped.exists() else qs
    return qs.first()


def featured_for(state: str, district: str) -> dict | None:
    """The product a place is known for, with what the platform has on it: today's rate, what to make from it, live offers."""
    from market.models import Listing

    odop = odop_for(state, district)
    if odop is None:
        return None
    crops = [c for c in odop.crops if c in PRODUCTS]
    rate = None
    for c in crops:
        rate = rate_services.typical_price(c, odop.state, odop.district)
        if rate:
            rate = {**rate, "crop": c}
            break
    offers = Listing.live().filter(district__iexact=odop.district, crop__in=crops).count() if crops else 0
    options = value_options(crops[0], odop.state, odop.district)[:3] if crops else []
    return {"odop": odop, "crops": crops, "rate": rate, "offers": offers, "options": options, "crop": crops[0] if crops else ""}


def featured_districts(state: str = "", limit: int = 12) -> list[dict]:
    """For buyers: places known for a product, those with live offers first."""
    from django.db.models import Count

    from market.models import Listing

    live = dict(Listing.live().values_list("district").annotate(n=Count("id")).values_list("district", "n"))
    qs = DistrictProduct.objects.all()
    if state:
        qs = qs.filter(state__iexact=state)
    rows = [{"odop": d, "offers": live.get(d.district, 0), "crop": (d.crops or [""])[0]} for d in qs]
    rows.sort(key=lambda r: (-r["offers"], r["odop"].district))
    return rows[:limit]
