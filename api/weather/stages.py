"""Where a crop is in its life, from the sowing date in the Farmer Book.

Durations are typical days from sowing to harvest; real ones vary with variety and weather, so stages are approximate.
"""
from datetime import date, timedelta

DAYS = {
    "wheat": 130, "rice": 130, "maize": 100, "jowar": 110, "bajra": 85, "ragi": 110, "barley": 120, "kodo": 100, "kutki": 80, "sawa": 75,
    "gram": 110, "tur": 160, "moong": 70, "urad": 80, "lentil": 120, "mustard": 120, "soybean": 100, "groundnut": 110, "sesame": 90,
    "sunflower": 95, "safflower": 130, "cotton": 170, "sugarcane": 330, "onion": 130, "potato": 100, "tomato": 120, "green_chilli": 150,
    "red_chilli": 150, "garlic": 140, "ginger": 240, "brinjal": 140, "cauliflower": 100, "cabbage": 100, "okra": 90, "peas": 90,
    "carrot": 90, "spinach": 45, "turmeric": 240, "coriander": 100, "mushroom": 30, "moringa_leaf": 60,
}
PERENNIAL = {"banana", "mango", "orange", "guava", "papaya", "pomegranate", "lemon", "custard_apple", "aonla"}
STAGES = [(0.15, "sowing"), (0.45, "growing"), (0.65, "flowering"), (0.9, "filling"), (1.15, "harvest")]
LABELS = {"sowing": "Sowing and early growth", "growing": "Growing", "flowering": "Flowering", "filling": "Grain or fruit forming",
          "harvest": "Ready to harvest", "stored": "Harvested, in storage", "orchard": "Orchard", "unknown": "Stage not known"}


def stage_of(cycle, today: date | None = None, in_stock: bool = False) -> str:
    today = today or date.today()
    if cycle.status in ("harvested", "closed"):
        return "stored" if in_stock else ""
    if cycle.crop in PERENNIAL:
        return "orchard"
    total = DAYS.get(cycle.crop)
    sown = cycle.sowing_date
    if sown is None and cycle.expected_harvest_date and total:
        sown = cycle.expected_harvest_date - timedelta(days=total)
    if sown is None or not total:
        return "unknown"
    if cycle.expected_harvest_date and cycle.sowing_date:
        total = max(20, (cycle.expected_harvest_date - cycle.sowing_date).days)
    frac = (today - sown).days / total
    if frac < 0:
        return "unknown"
    for upto, name in STAGES:
        if frac <= upto:
            return name
    return "harvest"
