"""A rate source yields plain dicts. To add another free public source, write a class with `name` and `fetch()` and register it in rates.ingest.SOURCES."""
from datetime import date
from decimal import Decimal, InvalidOperation


def to_price(value) -> Decimal | None:
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d > 0 else None


def parse_date(text) -> date | None:
    text = str(text or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
