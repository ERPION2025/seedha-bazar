"""Turn the official ODOP wording ("Tomato based Products", "Kodo-Kutki") into catalog crop keys."""
import re

# Longest and most specific first. Each entry: words to find in the lower-case text -> crops they mean.
WORDS = [
    (("kodo",), ["kodo"]), (("kutki",), ["kutki"]), (("sawa",), ["sawa"]), (("ragi", "finger millet", "hill millet"), ["ragi"]),
    (("jowar", "sorghum"), ["jowar"]), (("bajra",), ["bajra"]), (("millet",), ["ragi", "jowar", "bajra"]),
    (("tomato",), ["tomato"]), (("potato",), ["potato"]), (("onion",), ["onion"]), (("garlic",), ["garlic"]), (("ginger",), ["ginger"]),
    (("green pea", "peas"), ["peas"]), (("chilli", "chilly"), ["red_chilli", "green_chilli"]), (("turmeric",), ["turmeric"]),
    (("coriander",), ["coriander"]), (("mustard",), ["mustard"]), (("sugarcane", "jaggery"), ["sugarcane"]),
    (("guava",), ["guava"]), (("mango",), ["mango"]), (("banana",), ["banana"]), (("custard apple",), ["custard_apple"]),
    (("aonla", "amla"), ["aonla"]), (("orange", "citrus", "mandarin", "sweet orange"), ["orange"]), (("lemon",), ["lemon"]),
    (("pomegranate",), ["pomegranate"]), (("papaya",), ["papaya"]), (("mushroom",), ["mushroom"]),
    (("groundnut",), ["groundnut"]), (("sesamum", "sesame"), ["sesame"]), (("soyabean", "soybean"), ["soybean"]), (("sunflower",), ["sunflower"]),
    (("rice", "paddy", "poha", "murmura"), ["rice"]), (("maize",), ["maize"]), (("wheat",), ["wheat"]),
    (("pulse", "dal", "gram", "pigeon pea", "tur", "moong"), ["gram", "tur", "moong"]),
]


def crops_for(text: str) -> list[str]:
    t = " " + re.sub(r"[^a-z]+", " ", (text or "").lower()) + " "
    out: list[str] = []
    for words, crops in WORDS:
        if any(f" {w} " in t or (len(w) > 4 and w in t) for w in words):
            for c in crops:
                if c not in out:
                    out.append(c)
    return out
