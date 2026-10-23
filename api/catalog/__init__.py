"""The product catalog: names, kinds and conversions. See data.py. No database needed to read it."""
from .data import CONVERSIONS, FRESH, NEEDS, PRODUCTS, RAW, SEMI  # noqa: F401


def name(key: str) -> str:
    """English name of a product, or a tidied version of whatever a seller typed for something we do not list."""
    p = PRODUCTS.get(key)
    return p[0] if p else (key or "").strip().replace("_", " ").title()


def kind(key: str) -> str:
    p = PRODUCTS.get(key)
    return p[4] if p else RAW


def emoji(key: str) -> str:
    p = PRODUCTS.get(key)
    return p[3] if p else "🌾"


def keys_of(*kinds: str) -> list[str]:
    return [k for k, v in PRODUCTS.items() if v[4] in kinds]
