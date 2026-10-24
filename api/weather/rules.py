"""Turn a forecast and a crop's stage into short, specific advice. Thresholds are general agronomy rules of thumb; KVKs can refine them."""

FROST_SENSITIVE = {"potato", "tomato", "mustard", "gram", "peas", "brinjal", "green_chilli", "red_chilli", "banana", "papaya", "lentil", "coriander", "sugarcane"}
HEAT_SENSITIVE_RABI = {"wheat", "barley", "gram", "mustard", "lentil", "peas"}
BLIGHT_PRONE = {"potato", "tomato"}
RUST_PRONE = {"wheat", "barley"}

RAIN = {
    "harvest": "Heavy rain is likely. Harvest what is ready before it, or cover the cut crop.",
    "filling": "Heavy rain is likely. Keep field drains open so water does not stand.",
    "flowering": "Heavy rain is likely at flowering. Do not spray before it, and keep drains open.",
    "growing": "Heavy rain is likely. Keep field drains open and hold fertiliser until after it.",
    "sowing": "Heavy rain is likely. Wait to sow until after it, or make sure the field drains.",
    "stored": "Heavy rain is likely. Keep stored produce covered and off the floor.",
    "orchard": "Heavy rain is likely. Clear drains around the trees.",
}
FROST = "Frost is likely tonight. Give a light irrigation in the evening and make smoke on the field edges."
HEAT = {"flowering": "Very hot day ahead at flowering. Irrigate lightly in the early morning or evening.",
        "filling": "Very hot day ahead while the grain fills. A light irrigation helps it fill.",
        "default": "Very hot day ahead. Water in the morning or evening, not at midday."}
WIND = "Strong wind is likely. Do not spray, and support tall or heavy crops."
DRY = "Almost no rain in the next week. Plan a protective irrigation if you can."
BLIGHT = "Humid, cool weather favours blight. Check the leaves and ask the KVK if you see spots."
RUST = "Humid, cool weather favours rust. Check the leaves for orange or yellow powder."
ALL_TEXTS = list(RAIN.values()) + [FROST, *HEAT.values(), WIND, DRY, BLIGHT, RUST]


def advise(crop: str, stage: str, days: list[dict], season: str = "") -> list[dict]:
    """[{kind, day, advice, value}] for the coming days (at most one alert of each kind)."""
    if not stage or stage == "unknown":
        stage = "growing"
    out, seen = [], set()

    def add(kind, day, advice, value, critical=False):
        if kind not in seen:
            seen.add(kind)
            out.append({"kind": kind, "day": day, "advice": advice, "value": value, "severity": "critical" if critical else "warning"})

    for d in days[:5]:
        rain, prob = d.get("rain_mm") or 0, d.get("rain_prob") or 0
        if rain >= 25 or (rain >= 15 and prob >= 70):
            add("rain", d["date"], RAIN.get(stage, RAIN["growing"]), f"{rain:.0f} mm", critical=rain >= 50 or stage in ("harvest", "stored", "sowing"))
        if d.get("tmin") is not None and d["tmin"] <= 4 and crop in FROST_SENSITIVE and stage in ("sowing", "growing", "flowering", "filling", "orchard"):
            add("frost", d["date"], FROST, f"{d['tmin']:.0f}°C", critical=d["tmin"] <= 2 or stage in ("flowering", "filling"))
        hot = 34 if crop in HEAT_SENSITIVE_RABI and stage in ("flowering", "filling") else 40
        if d.get("tmax") is not None and d["tmax"] >= hot and stage in ("sowing", "growing", "flowering", "filling", "orchard"):
            add("heat", d["date"], HEAT.get(stage, HEAT["default"]), f"{d['tmax']:.0f}°C", critical=d["tmax"] >= hot + 4)
        if (d.get("gust") or 0) >= 45 and stage in ("growing", "flowering", "filling", "harvest", "orchard"):
            add("wind", d["date"], WIND, f"{d['gust']:.0f} km/h", critical=d["gust"] >= 60)
        hum, tmax = d.get("humidity") or 0, d.get("tmax") or 0
        if hum >= 85 and 15 <= tmax <= 28 and stage in ("growing", "flowering", "filling"):
            if crop in BLIGHT_PRONE:
                add("disease", d["date"], BLIGHT, f"{hum:.0f}%")
            elif crop in RUST_PRONE:
                add("disease", d["date"], RUST, f"{hum:.0f}%")
    week = days[:7]
    if season == "kharif" and stage in ("growing", "flowering") and week and sum((d.get("rain_mm") or 0) for d in week) < 2 and max((d.get("tmax") or 0) for d in week) >= 33:
        add("dry", week[0]["date"], DRY, f"{sum((d.get('rain_mm') or 0) for d in week):.0f} mm / 7")
    return out
