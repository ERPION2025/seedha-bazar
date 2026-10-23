"""The calculator's arithmetic. static/web/calculator.js does the same sums for the screen; this copy builds the SMS and
WhatsApp text, so a message never depends on numbers sent from the browser."""
from decimal import Decimal, InvalidOperation

KG = {"kg": Decimal(1), "quintal": Decimal(100), "tonne": Decimal(1000)}


def _n(value) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return d if d.is_finite() and d > 0 else Decimal(0)


def _r(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"))


def compute(i: dict) -> dict:
    unit = i.get("unit", "quintal")
    per = _n(i.get("bagKg")) if unit == "bag" else KG.get(unit, Decimal(100))
    qty_kg = _n(i.get("qty")) * per
    qtl = qty_kg / 100
    rate_per_qtl = _n(i.get("rate")) * (Decimal(100) if i.get("rateUnit") == "kg" else Decimal(1))
    gross = qtl * rate_per_qtl
    commission = gross * _n(i.get("commissionPct")) / 100
    cut = commission + _n(i.get("fees")) + _n(i.get("other"))
    hand = gross - cut - _n(i.get("transport"))
    out = {"qty_kg": _r(qty_kg), "gross": _r(gross), "commission": _r(commission), "cut": _r(cut), "hand": _r(hand)}
    if _n(i.get("directRate")) > 0 and qtl > 0:
        out["direct"] = _r(qtl * _n(i.get("directRate")) - _n(i.get("directTransport")))
        out["gap"] = _r(out["direct"] - hand)
    return out
