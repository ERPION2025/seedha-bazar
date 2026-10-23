"""Store-or-sell sums, pledge records, and due-date reminders.

Typical terms (check with the bank; they change): banks lend up to about 70-75% of the stored value against an e-NWR;
Kisan Credit Card holders can get pledge loans at about 7% a year for up to 6 months under the interest subvention scheme;
an e-NWR is valid for at most 12 months. See https://wdra.gov.in/ekun-eng (e-Kisan Upaj Nidhi).
"""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from accounts.errors import ApiError
from notify import service as notify

from .models import Pledge, Warehouse

D = Decimal
DEFAULT_LTV = D("70")
KCC_RATE = D("7")
MAX_KCC_MONTHS = 6


def pledged_kg(cycle, product: str) -> D:
    """Kg of this stock lying pledged in a warehouse: it cannot be listed until the loan is cleared."""
    return Pledge.objects.filter(crop_cycle=cycle, product=product, status__in=["stored", "loan"]).aggregate(t=Sum("quantity_kg"))["t"] or D(0)


def store_or_sell(quantity_kg: D, price_now_q: D, months: int, storage_rate_q_month: D, ltv_pct: D = DEFAULT_LTV, rate_pct: D = KCC_RATE) -> dict:
    """Compare selling now with storing for `months`, borrowing against the receipt meanwhile.

    Returns the loan you could get, what storing and interest would cost, and the price per quintal you would need later to come out ahead.
    """
    q = quantity_kg / 100
    value = (q * price_now_q).quantize(D("1"))
    loan = (value * ltv_pct / 100).quantize(D("1"), rounding=ROUND_HALF_UP)
    storage = (q * storage_rate_q_month * months).quantize(D("1"))
    interest = (loan * rate_pct / 100 * months / 12).quantize(D("1"))
    breakeven = ((value + storage + interest) / q).quantize(D("1")) if q else D(0)
    return {"value": value, "loan": loan, "storage": storage, "interest": interest, "cost": storage + interest, "breakeven_q": breakeven,
            "rise_pct": ((breakeven - price_now_q) / price_now_q * 100).quantize(D("0.1")) if price_now_q else D(0)}


def warehouses_near(state: str, district: str):
    """WDRA-registered warehouses in the district (active ones first, biggest first), then a few more from the state."""
    from django.db.models import Case, IntegerField, Value, When

    qs = (Warehouse.objects.filter(state__iexact=state).exclude(wdra_status__in=["Not listed", "Cancelled", "Surrendered"])
          .annotate(rank=Case(When(wdra_status__iexact="Active", then=Value(0)), When(wdra_status="", then=Value(1)), default=Value(2), output_field=IntegerField()))
          .order_by("rank", "-capacity_mt"))
    near = list(qs.filter(Q(district__iexact=district) | Q(district__istartswith=(district or "").split("(")[0].strip()))[:60])
    rest = list(qs.exclude(pk__in=[w.pk for w in near])[:20])
    return near, rest


def plan(farmer, cycle, product: str, quantity_kg: D, warehouse=None, note: str = "") -> Pledge:
    from market import stock

    if cycle.owner_id != farmer.pk:
        raise ApiError("not_allowed", "You cannot do this.", 403)
    if quantity_kg is None or quantity_kg <= 0:
        raise ApiError("bad_quantity", "Enter a quantity more than zero.", 400)
    free = stock.free_kg(cycle, product)
    if quantity_kg > free:
        raise ApiError("not_enough_stock", "That is more than the stock in your book that is not already listed.", 400, available_kg=str(free))
    return Pledge.objects.create(farmer=farmer, crop_cycle=cycle, product=product, quantity_kg=quantity_kg, warehouse=warehouse, note=(note or "")[:300])


def record_deposit(p: Pledge, enwr_no: str, deposit_date, repository: str, valid_until=None, value=None) -> Pledge:
    if p.status not in ("planned", "stored"):
        raise ApiError("not_now", "This step is not open yet.", 409)
    if not (enwr_no or "").strip():
        raise ApiError("number_needed", "Write the e-NWR number from the warehouse.", 400)
    p.enwr_no, p.deposit_date, p.repository = enwr_no.strip()[:60], deposit_date, repository if repository in ("nerl", "ccrl") else ""
    p.valid_until = valid_until or (deposit_date + timedelta(days=365) if deposit_date else None)
    p.value_at_deposit = value
    p.status = Pledge.Status.STORED
    p.save()
    return p


def record_loan(p: Pledge, bank: str, amount, rate, loan_date, due_date) -> Pledge:
    if p.status not in ("stored", "loan"):
        raise ApiError("not_now", "This step is not open yet.", 409)
    if not amount or amount <= 0:
        raise ApiError("bad_amount", "Enter the amount paid.", 400)
    if due_date and loan_date and due_date <= loan_date:
        raise ApiError("bad_date", "Choose a delivery date after today.", 400)
    p.bank, p.loan_amount, p.interest_pct, p.loan_date, p.due_date = bank[:120], amount, rate, loan_date, due_date
    p.status = Pledge.Status.LOAN
    p.save()
    return p


def close(p: Pledge) -> Pledge:
    p.status = Pledge.Status.CLOSED
    p.save()
    return p


def remind_due(today=None) -> int:
    """Text farmers 15 days and 3 days before a pledge loan or an e-NWR falls due."""
    from web.i18n import tr
    import catalog

    today = today or timezone.localdate()
    n = 0
    for p in Pledge.objects.filter(status__in=["stored", "loan"]).select_related("farmer"):
        due = p.due_date if p.status == "loan" else p.valid_until
        if not due:
            continue
        left = (due - today).days
        if left in (15, 3) and not (p.reminded_at and p.reminded_at.date() == today):
            u = p.farmer
            notify.send("sms", u.phone, "pledge_due", u.language, user=u, related=f"pledge:{p.pk}", product=tr(u.language, catalog.name(p.product)),
                        date=due.strftime("%d %b %Y"), link=f"{settings.SITE_URL}/storage/")
            p.reminded_at = timezone.now()
            p.save(update_fields=["reminded_at"])
            n += 1
    return n


def tidy(s: str) -> str:
    """WDRA writes many names in capitals; show them in plain Title Case."""
    s = " ".join((s or "").replace(",,", ",").split()).strip(" ,.-")
    return s.title() if s.isupper() or s.islower() else s


def locality(w) -> str:
    """A short 'where is it': the first useful parts of the address, without khasra numbers and repeats of the district."""
    import re

    parts = [tidy(p) for p in re.split(r"[,;]", w.address or "") if p.strip()]
    keep = []
    for p in parts:
        low = p.lower()
        if re.search(r"\b(khasra|kh\.?\s?no|survey|s\.?\s?no|plot|ph\.?\s?no|patwari)\b", low) or low in (w.district or "").lower() or "district" in low:
            continue
        p = re.sub(r"^(vill(age)?|gram|post|tehsil|teh)\.?\s*[-:.]?\s*", "", p, flags=re.I).strip()
        if p and p.lower() not in [k.lower() for k in keep]:
            keep.append(p)
        if len(keep) == 2:
            break
    return ", ".join(keep)


def warehouse_list(state: str, district: str = "", q: str = "", active_only: bool = True, near: list[str] | None = None):
    """Registered warehouses to choose from: in a district (or the whole state), matching a place or name, active first.

    Warehouses whose address mentions the person's own village or block come first."""
    from django.db.models import Case, IntegerField, Value, When

    qs = Warehouse.objects.filter(state__iexact=state).exclude(wdra_status__in=["Not listed", "Cancelled", "Surrendered"])
    if district:
        qs = qs.filter(Q(district__iexact=district) | Q(district__istartswith=district.split("(")[0].strip()))
    if active_only:
        qs = qs.filter(Q(wdra_status__iexact="Active") | Q(wdra_status=""))
    for word in (q or "").split()[:4]:
        qs = qs.filter(Q(address__icontains=word) | Q(name__icontains=word) | Q(operator__icontains=word))
    near_q = Q()
    for word in [w for w in (near or []) if w and len(w) > 2]:
        near_q |= Q(address__icontains=word)
    rank = [When(near_q, then=Value(0))] if near_q else []
    return qs.annotate(near=Case(*rank, default=Value(1), output_field=IntegerField())).order_by("near", "-capacity_mt", "name")


def warehouse_districts(state: str) -> list[str]:

    return sorted({d.strip().title() for d in Warehouse.objects.filter(state__iexact=state).exclude(wdra_status__in=["Not listed"]).values_list("district", flat=True) if d})
