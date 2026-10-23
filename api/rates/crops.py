"""The crops Seedha Bazar knows by name, and how mandi commodity names map onto them."""

CROPS = {
    "wheat": "Wheat", "rice": "Rice", "soybean": "Soybean", "maize": "Maize", "gram": "Gram (chana)",
    "lentil": "Lentil (masoor)", "mustard": "Mustard", "tur": "Tur (arhar)", "moong": "Moong (green gram)",
    "urad": "Urad (black gram)", "kodo": "Kodo millet", "kutki": "Kutki millet", "sawa": "Sawa millet",
    "ragi": "Ragi", "jowar": "Jowar", "bajra": "Bajra", "barley": "Barley", "groundnut": "Groundnut",
    "sunflower": "Sunflower", "sesame": "Sesame (til)", "safflower": "Safflower", "cotton": "Cotton",
    "sugarcane": "Sugarcane", "onion": "Onion", "potato": "Potato", "tomato": "Tomato",
}

EMOJI = {
    "wheat": "🌾", "rice": "🍚", "soybean": "🫘", "maize": "🌽", "gram": "🫘", "lentil": "🫘", "mustard": "🌼",
    "tur": "🫘", "moong": "🫘", "urad": "🫘", "kodo": "🌾", "kutki": "🌾", "sawa": "🌾", "ragi": "🌾", "jowar": "🌾",
    "bajra": "🌾", "barley": "🌾", "groundnut": "🥜", "sunflower": "🌻", "sesame": "⚪", "safflower": "🌼",
    "cotton": "☁️", "sugarcane": "🎋", "onion": "🧅", "potato": "🥔", "tomato": "🍅",
}

# Order matters: the first rule that matches wins. Patterns are matched against the lower-case commodity name.
RULES = [
    ("moong", ("green gram", "moong")),
    ("urad", ("black gram", "urd", "urad")),
    ("gram", ("bengal gram", "chickpea", "chana")),
    ("tur", ("arhar", "red gram", "pigeon", "tur(", "tur (")),
    ("lentil", ("lentil", "masur")),
    ("wheat", ("wheat",)),
    ("rice", ("paddy", "rice")),
    ("soybean", ("soyabean", "soybean", "soya")),
    ("maize", ("maize",)),
    ("mustard", ("mustard", "rapeseed")),
    ("kodo", ("kodo",)),
    ("kutki", ("kutki", "little millet")),
    ("sawa", ("sawa", "barnyard", "sanwa")),
    ("ragi", ("ragi", "finger millet")),
    ("jowar", ("jowar", "sorghum")),
    ("bajra", ("bajra", "pearl millet")),
    ("barley", ("barley",)),
    ("groundnut", ("groundnut", "peanut")),
    ("sunflower", ("sunflower",)),
    ("sesame", ("sesamum", "sesame")),
    ("safflower", ("safflower",)),
    ("cotton", ("cotton",)),
    ("onion", ("onion",)),
    ("potato", ("potato",)),
    ("tomato", ("tomato",)),
]


def canonical_crop(commodity: str) -> str:
    """'Bengal Gram(Gram)(Whole)' -> 'gram'. Returns '' for anything we do not track (dals, oils, seeds, sweet potato...)."""
    name = (commodity or "").strip().lower()
    if not name:
        return ""
    if name.endswith("dal") or " dal" in name or "dal(" in name or "oil" in name or "seed" in name and "cotton" in name:
        return ""
    if "sweet potato" in name:
        return ""
    for key, patterns in RULES:
        if any(p in name for p in patterns):
            return key
    return ""
