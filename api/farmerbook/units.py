from decimal import Decimal

KG_PER = {"kg": Decimal("1"), "quintal": Decimal("100"), "tonne": Decimal("1000")}
UNITS = ["kg", "quintal", "tonne", "bag"]


def to_kg(quantity: Decimal, unit: str, bag_weight_kg: Decimal | None = None) -> Decimal:
    if unit == "bag":
        if not bag_weight_kg:
            raise ValueError("bag_weight_kg is required when the unit is bag")
        return (quantity * bag_weight_kg).quantize(Decimal("0.001"))
    return (quantity * KG_PER[unit]).quantize(Decimal("0.001"))
