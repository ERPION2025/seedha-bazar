from decimal import Decimal

KG_PER = {"kg": Decimal("1"), "quintal": Decimal("100"), "tonne": Decimal("1000"),
          # livelihood products: milk by the litre, eggs by the tray of 30, piglets by the piece (a nominal kg, used only for sorting)
          "litre": Decimal("1.03"), "tray": Decimal("1.8"), "piece": Decimal("1")}
UNITS = ["kg", "quintal", "tonne", "bag", "litre", "tray", "piece"]


def to_kg(quantity: Decimal, unit: str, bag_weight_kg: Decimal | None = None) -> Decimal:
    if unit == "bag":
        if not bag_weight_kg:
            raise ValueError("bag_weight_kg is required when the unit is bag")
        return (quantity * bag_weight_kg).quantize(Decimal("0.001"))
    return (quantity * KG_PER[unit]).quantize(Decimal("0.001"))
