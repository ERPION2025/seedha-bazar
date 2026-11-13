"""GST documents for shop orders, issued when the goods leave (dispatch) or are handed over (pickup).

- A GST-registered seller's goods get a tax invoice; an unregistered or exempt seller's goods get a bill of supply.
  Prices on Seedha Bazar include GST, so the taxable value is worked back from the price.
- Same state for supplier and delivery: CGST + SGST, half each; different states: IGST.
- Seedha Bazar's own charges (its buyer fee and delivery) get its service invoice (SAC 998599) when it is GST-registered.
- As the e-commerce operator, Seedha Bazar keeps TCS (section 52) on a registered seller's taxable value; it is taken from
  that seller's payout.
Rates and rules change: confirm the set-up with a chartered accountant before going live.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Invoice

D = Decimal
P = D("0.01")


def q(x) -> Decimal:
    return D(x).quantize(P, rounding=ROUND_HALF_UP)


def split(amount: Decimal, rate: Decimal, intra: bool) -> dict:
    """GST included in `amount` at `rate` %, as taxable value and CGST/SGST or IGST."""
    taxable = q(amount * 100 / (100 + rate)) if rate else q(amount)
    tax = q(amount) - taxable
    half = q(tax / 2)
    return {"taxable": taxable, "cgst": half if intra else D(0), "sgst": tax - half if intra else D(0), "igst": D(0) if intra else tax, "total": q(amount)}


def tcs_for(amount: Decimal, rate: Decimal, seller_gstin: str) -> Decimal:
    if not (settings.GSTIN and seller_gstin):
        return D(0)
    return q(split(amount, rate, True)["taxable"] * D(settings.GST_TCS_PCT) / 100)


def _fy(now=None) -> str:
    now = timezone.localdate(now)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def _number(prefix: str) -> str:
    fy = _fy()
    stem = f"{prefix}/{fy}/"
    n = Invoice.objects.filter(number__startswith=stem).count() + 1
    return f"{stem}{n:05d}"


def _buyer(order) -> dict:
    return {"name": order.name, "address": f"{order.address}, {order.city} {order.pincode}", "state": order.state, "gstin": order.gstin}


@transaction.atomic
def issue(order) -> list:
    """Issue the order's documents once. Returns those issued now."""
    if order.invoices.exists() or order.status == "cancelled":
        return []
    from .models import SellerSettings

    made = []
    place = order.state
    sellers = {}
    for line in order.lines.select_related("seller__farmer_profile"):
        sellers.setdefault(line.seller, []).append(line)
    for seller, lines in sellers.items():
        ss = SellerSettings.objects.filter(user=seller).first()
        fp = getattr(seller, "farmer_profile", None)
        sup_state = (ss.state if ss and ss.state else getattr(fp, "state", "")) or settings.GST_STATE
        registered = bool(ss and ss.gstin)
        intra = sup_state.lower() == (place or "").lower()
        rows, totals = [], {"taxable": D(0), "cgst": D(0), "sgst": D(0), "igst": D(0), "total": D(0)}
        for l in lines:
            s = split(l.amount, l.gst_rate if registered else D(0), intra)
            rows.append({"item": l.title, "pack": l.pack, "hsn": l.hsn, "qty": l.quantity, "rate": str(l.gst_rate if registered else 0), **{k: str(v) for k, v in s.items()}})
            for k in totals:
                totals[k] += s[k]
        name = (ss.legal_name if ss and ss.legal_name else getattr(fp, "name", "")) or seller.phone
        inv = Invoice.objects.create(order=order, seller=seller, kind="tax" if registered else "supply", number=_number(f"S{seller.pk}"), data={
            "supplier": {"name": name, "gstin": ss.gstin if ss else "", "address": ", ".join(x for x in ((ss.address, ss.district, ss.state) if ss else ()) if x), "state": sup_state},
            "buyer": _buyer(order), "place_of_supply": place, "intra": intra, "lines": rows, "totals": {k: str(v) for k, v in totals.items()},
            "operator": {"name": "Seedha Bazar (" + settings.COMPANY_NAME + ")", "gstin": settings.GSTIN},
            "note": "" if registered else "Supplier not registered under GST / exempt supply: bill of supply, no GST charged."})
        made.append(inv)
    service = q(order.buyer_fee + order.delivery_fee)
    if service:
        registered = bool(settings.GSTIN)
        intra = settings.GST_STATE.lower() == (place or "").lower()
        s = split(service, D(settings.GST_SERVICE_RATE) if registered else D(0), intra)
        inv = Invoice.objects.create(order=order, seller=None, kind="platform", number=_number("SB"), data={
            "supplier": {"name": settings.COMPANY_NAME, "gstin": settings.GSTIN, "address": settings.COMPANY_ADDRESS, "state": settings.GST_STATE},
            "buyer": _buyer(order), "place_of_supply": place, "intra": intra,
            "lines": [{"item": "Marketplace service and delivery arranged by Seedha Bazar", "pack": "", "hsn": "998599", "qty": 1,
                       "rate": settings.GST_SERVICE_RATE if registered else "0", **{k: str(v) for k, v in s.items()}}],
            "totals": {k: str(v) for k, v in s.items()}, "operator": {}, "note": "" if registered else "Seedha Bazar is not yet registered under GST: no GST charged."})
        made.append(inv)
    return made
