"""Questions the website asks about prices. Everything here is read-only and fast."""
from datetime import timedelta
from decimal import Decimal
from statistics import median

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .crops import CROPS
from .models import MarketRate, MspPrice

FRESH_DAYS = 10  # a market's price older than this is not shown as "today's"


def usable():
    qs = MarketRate.objects.exclude(crop="")
    return qs if settings.RATES_SHOW_DEMO else qs.exclude(source="demo")


def _norm(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def latest_per_market(crop: str, state: str = "", district: str = "", days: int = FRESH_DAYS) -> list[dict]:
    """One row per mandi: its most recent price for this crop inside the window."""
    since = timezone.localdate() - timedelta(days=days)
    qs = usable().filter(crop=crop, date__gte=since)
    if state:
        qs = qs.filter(state__iexact=state)
    if district:
        qs = qs.filter(district__iexact=district)
    groups: dict[tuple, list[MarketRate]] = {}
    newest: dict[tuple, object] = {}
    for r in qs.order_by("-date")[:5000]:
        key = (r.state, r.district, r.market)
        if key not in newest:
            newest[key] = r.date
        if r.date == newest[key]:
            groups.setdefault(key, []).append(r)
    rows = []
    for (st, dist, market), rs in groups.items():
        rs.sort(key=lambda r: r.modal_price)
        pick = rs[len(rs) // 2]  # when a mandi reports several varieties, take the middle one
        rows.append({"market": market, "district": dist, "state": st, "date": pick.date, "min": pick.min_price, "max": pick.max_price,
                     "modal": pick.modal_price, "demo": pick.source == "demo"})
    return rows


def msp_for(crop: str) -> dict | None:
    row = MspPrice.objects.filter(crop=crop).order_by("-announced_on", "-season").first()
    if row is None:
        return None
    return {"price": row.price_per_quintal, "season": row.season, "name": row.name, "url": row.source_url}


def trend_pct(crop: str, state: str, district: str = "") -> Decimal | None:
    """Change in the typical price over about a week, in percent. None when there is not enough history."""
    today = timezone.localdate()

    def typical(start, end):
        qs = usable().filter(crop=crop, date__gte=start, date__lte=end)
        if state:
            qs = qs.filter(state__iexact=state)
        if district:
            qs = qs.filter(district__iexact=district)
        prices = list(qs.values_list("modal_price", flat=True)[:3000])
        return median(prices) if len(prices) >= 3 else None

    now, before = typical(today - timedelta(days=3), today), typical(today - timedelta(days=10), today - timedelta(days=5))
    if not now or not before:
        return None
    return ((Decimal(now) - Decimal(before)) / Decimal(before) * 100).quantize(Decimal("0.1"))


def quote(crop: str, state: str = "", district: str = "") -> dict:
    """Everything the calculator and rates page need for one crop in one place.

    `local` are mandis in the person's district; `nearby` the best-paying others in the state. `typical` is the number
    used to fill in the form: the district's middle price, else the state's, else None.
    """
    state_rows = latest_per_market(crop, state) if state else latest_per_market(crop)
    local = [r for r in state_rows if district and _norm(r["district"]) == _norm(district)]
    others = [r for r in state_rows if r not in local]
    local.sort(key=lambda r: (-r["date"].toordinal(), r["market"]))
    others.sort(key=lambda r: (-r["modal"], r["market"]))
    pool = local or state_rows
    typical = Decimal(median([r["modal"] for r in pool])).quantize(Decimal("1")) if pool else None
    as_of = max((r["date"] for r in pool), default=None)
    return {
        "crop": crop, "label": CROPS.get(crop, crop.title()), "state": state, "district": district,
        "scope": "district" if local else "state" if state_rows and state else "india" if state_rows else "none",
        "typical": typical, "as_of": as_of, "local": local[:6], "nearby": others[:6], "count": len(state_rows),
        "msp": msp_for(crop), "trend": trend_pct(crop, state, district if local else "") if pool else None,
        "demo": any(r["demo"] for r in pool),
    }


def typical_price(crop: str, state: str = "", district: str = "") -> dict | None:
    """The middle recent mandi price for a place, cheaply (one query). None when there is no data."""
    rows = latest_per_market(crop, state)
    local = [r for r in rows if district and _norm(r["district"]) == _norm(district)]
    pool = local or rows
    if not pool:
        return None
    return {"typical": Decimal(median([r["modal"] for r in pool])).quantize(Decimal("1")), "as_of": max(r["date"] for r in pool),
            "scope": "district" if local else "state", "demo": any(r["demo"] for r in pool)}


def crop_prices(state: str = "", district: str = "") -> list[dict]:
    """For the crop tiles: each crop that has data, with a typical price for the place. Most-reported crops first."""
    since = timezone.localdate() - timedelta(days=FRESH_DAYS)
    base = usable().filter(date__gte=since)
    if state:
        scoped = base.filter(state__iexact=state)
        base = scoped if scoped.exists() else base
    counts = dict(base.values_list("crop").annotate(n=Count("id")).values_list("crop", "n"))
    out = []
    for crop, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if crop not in CROPS:
            continue
        q = quote(crop, state, district)
        if q["typical"] is not None:
            out.append({"crop": crop, "typical": q["typical"], "as_of": q["as_of"], "scope": q["scope"]})
    return out


def places() -> dict[str, list[str]]:
    """{state: [districts]} from recent data, for the manual place picker."""
    since = timezone.localdate() - timedelta(days=30)
    out: dict[str, set] = {}
    for st, dist in usable().filter(date__gte=since).values_list("state", "district").distinct():
        out.setdefault(st, set()).add(dist)
    return {st: sorted(ds) for st, ds in sorted(out.items())}


def match_place(state: str, district: str) -> tuple[str, str]:
    """Map names from the map service onto the names mandis use. Returns ('', '') parts that cannot be matched."""
    import difflib

    known = places()

    def best(name, options):
        if not name:
            return ""
        n = _norm(name).replace("district", "")
        by_norm = {_norm(o): o for o in options}
        if n in by_norm:
            return by_norm[n]
        hit = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.8)
        return by_norm[hit[0]] if hit else ""

    st = best(state, known.keys())
    return st, best(district, known.get(st, [])) if st else ""


def last_update():
    from .models import RateFetchLog

    ok = RateFetchLog.objects.filter(status=RateFetchLog.Status.OK).first()
    return ok.finished_at if ok else None
