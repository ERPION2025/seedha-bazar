"""The crops Seedha Bazar knows by name, and how mandi commodity names map onto them."""

from catalog import FRESH, PRODUCTS, RAW

# Everything that is grown and reported by mandis: raw produce and fresh produce. Processed goods live in the catalog only.
CROPS = {k: v[0] for k, v in PRODUCTS.items() if v[4] in (RAW, FRESH)}
EMOJI = {k: v[3] for k, v in PRODUCTS.items() if v[4] in (RAW, FRESH)}

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
    # Fresh produce and spices. A "" key means "a commodity we know but keep out" (so dry ginger does not blend into green ginger).
    ("", ("ginger(dry)", "dry ginger", "peas(dry)", "peas dry", "sweet orange seed", "garlic(dry)", "dry garlic")),
    ("green_chilli", ("green chilli", "green chillies", "chilly green")),
    ("red_chilli", ("dry chillies", "dry chilli", "red chilli", "chillies(dry)")),
    ("garlic", ("garlic",)),
    ("ginger", ("ginger",)),
    ("brinjal", ("brinjal", "baingan")),
    ("cauliflower", ("cauliflower",)),
    ("cabbage", ("cabbage",)),
    ("okra", ("bhindi", "ladies finger", "okra")),
    ("peas", ("green peas", "peas wet", "peas(wet)", "peas (wet)", "peas cod")),
    ("carrot", ("carrot",)),
    ("spinach", ("spinach", "palak")),
    ("mushroom", ("mushroom",)),
    ("banana", ("banana",)),
    ("mango", ("mango",)),
    ("orange", ("orange", "mousambi", "mosambi", "sweet orange")),
    ("guava", ("guava",)),
    ("papaya", ("papaya",)),
    ("pomegranate", ("pomegranate",)),
    ("lemon", ("lemon",)),
    ("custard_apple", ("custard apple", "sitaphal")),
    ("aonla", ("amla", "aonla", "nelli")),
    ("turmeric", ("turmeric",)),
    ("coriander", ("coriander seed", "dhania", "coriander(seed)")),
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
            return key if key in CROPS else ""
    return ""
