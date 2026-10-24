from decimal import Decimal, InvalidOperation


def inr(value, places: int = 0) -> str:
    """Rupees with Indian digit grouping: 1234567 -> ₹12,34,567."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return "—"
    sign = "-" if d < 0 else ""
    d = abs(d).quantize(Decimal(1) if not places else Decimal("0.01"))
    whole, _, frac = f"{d:f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    if head:
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        tail = ",".join(groups) + "," + tail
    return f"{sign}₹{tail}" + (f".{frac}" if frac else "")
