"""Clearly-labelled sample rates so every screen has something to show before a data.gov.in key is set up. Never used in production."""
import hashlib
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import MarketRate

BASE = {  # rupees per quintal, roughly where each crop trades
    "Wheat": 2450, "Soyabean": 4400, "Bengal Gram(Gram)(Whole)": 5600, "Mustard": 5900, "Maize": 2150, "Paddy(Dhan)(Common)": 2300,
    "Arhar (Tur/Red Gram)(Whole)": 7200, "Lentil (Masur)(Whole)": 6400, "Kodo Millet(Kodon)": 3100, "Onion": 1800, "Potato": 1500,
    "Tomato": 2200, "Jowar(Sorghum)": 3300, "Bajra(Pearl Millet/Cumbu)": 2500, "Groundnut": 6300, "Cotton": 7000,
}
PLACES = {
    "Madhya Pradesh": {"Rewa": ["Rewa"], "Satna": ["Satna"], "Sidhi": ["Sidhi"], "Jabalpur": ["Jabalpur"], "Bhopal": ["Bhopal"], "Indore": ["Indore"], "Sagar": ["Sagar"]},
    "Maharashtra": {"Pune": ["Pune"], "Nashik": ["Lasalgaon"], "Nagpur": ["Nagpur"], "Latur": ["Latur"], "Akola": ["Akola"]},
}


def _wiggle(*parts, spread: float) -> float:
    h = int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return 1 + ((h % 2001) - 1000) / 1000 * spread


def seed_demo_rates(days: int = 14) -> int:
    today = timezone.localdate()
    from .crops import canonical_crop

    rows = []
    for state, districts in PLACES.items():
        for district, markets in districts.items():
            for market in markets:
                for commodity, base in BASE.items():
                    if state == "Maharashtra" and commodity.startswith("Kodo"):
                        continue
                    for d in range(days):
                        day = today - timedelta(days=d)
                        modal = Decimal(round(base * _wiggle(state, market, commodity, spread=0.06) * _wiggle(day, commodity, spread=0.02) * (1 - 0.0015 * d)))
                        rows.append(MarketRate(source="demo", date=day, state=state, district=district, market=f"{market}", commodity=commodity, variety="Other", grade="FAQ",
                                               crop=canonical_crop(commodity), min_price=modal - 120, max_price=modal + 140, modal_price=modal))
    MarketRate.objects.bulk_create(rows, update_conflicts=True, unique_fields=["source", "date", "state", "district", "market", "commodity", "variety", "grade"],
                                   update_fields=["min_price", "max_price", "modal_price", "crop"])
    return len(rows)
