"""The twelve free games: what they are, how many points each can give, and the words and questions they use.

All text is English here and translated through web/translations.py like the rest of the site.
"""
import catalog

GAMES = [
    # slug, emoji, title, one line, max points, voice
    ("quiz", "❓", "Kheti Quiz", "Answer farming questions. Tap or say the answer.", 100, True),
    ("price", "💰", "Guess the Price", "Guess today's mandi price. Closest guess wins.", 100, True),
    ("season", "🌦️", "Kharif or Rabi", "Put each crop in its season. Tap or say it.", 100, True),
    ("pests", "🐛", "Catch the Pests", "Tap the pests. Leave the farmer's friends alone.", 100, False),
    ("memory", "🃏", "Crop and Product Pairs", "Find each crop and what it becomes.", 100, False),
    ("catch", "🧺", "Save the Grain", "Move the basket to catch grain. Dodge the stones.", 100, False),
    ("water", "💧", "Water Wise", "Keep the soil moist, not flooded. Say 'water' or 'stop'.", 100, True),
    ("market", "🏪", "Best Market", "Pick where you get the most money in hand.", 100, True),
    ("sums", "🧮", "Quick Hisab", "Quantity times rate. Pick the right total.", 100, True),
    ("name", "🗣️", "Say the Crop", "Say the crop's name out loud, or tap it.", 100, True),
    ("weather", "⛈️", "Weather Wise", "Choose the right thing to do in each weather.", 100, True),
    ("sow", "🌱", "Sowing Rhythm", "Tap when the seed is over the furrow.", 100, False),
]
SLUGS = {g[0] for g in GAMES}
CAP = {g[0]: g[4] for g in GAMES}

QUIZ = [
    ("Which season is wheat sown in?", ["Rabi", "Kharif", "Zaid", "All year"], 0, "Wheat is a rabi crop, sown from October to December."),
    ("How much does a farmer pay for kharif crop insurance under PMFBY?", ["2% of the cover", "10% of the cover", "25% of the cover", "Nothing at all"], 0, "Farmers pay 2% for kharif food crops; the government pays the rest."),
    ("Which helpline gives free farming advice?", ["1800-180-1551", "100", "108", "139"], 0, "The Kisan Call Centre, 1800-180-1551, answers in your language."),
    ("From 100 kg of fresh mushroom, about how much dried mushroom do you get?", ["About 10 kg", "About 50 kg", "About 90 kg", "100 kg"], 0, "Mushroom is mostly water. Dried, it weighs about a tenth but sells for much more."),
    ("Which of these insects is a friend of the farmer?", ["Ladybird beetle", "Locust", "Armyworm", "Whitefly"], 0, "Ladybird beetles eat aphids that damage crops."),
    ("What does a Soil Health Card tell you?", ["Nutrients in your soil and the fertiliser to use", "Tomorrow's weather", "The mandi price", "Your loan limit"], 0, "A soil test shows what your field needs, so you do not waste fertiliser."),
    ("How much does PM-KISAN pay a year?", ["Rs 6,000", "Rs 600", "Rs 60,000", "Rs 16,000"], 0, "Rs 6,000 a year in three instalments."),
    ("Within how many hours should you report hail damage for insurance?", ["72 hours", "7 days", "1 month", "No need to report"], 0, "Report within 72 hours on the helpline, app or bank."),
    ("Which of these is made from gram (chana)?", ["Besan", "Atta", "Jaggery", "Poha"], 0, "Besan is gram flour."),
    ("What is MSP?", ["Minimum Support Price set by the government", "Market Selling Point", "Maximum Sale Price", "Mandi Service Payment"], 0, "MSP is the price at which the government buys certain crops."),
    ("Which crop is sown in kharif?", ["Soybean", "Wheat", "Mustard", "Gram"], 0, "Soybean is sown with the monsoon rains."),
    ("Why write your expenses in the Farmer Book?", ["To know your real profit", "To pay more tax", "Because buyers ask", "No reason"], 0, "Knowing your costs shows your real profit and the lowest price you can accept."),
]

WEATHER = [
    ("Heavy rain is forecast tomorrow and your cut wheat is lying in the field.", ["Cover it or move it to a dry place", "Spray fertiliser", "Start irrigation"], 0, "Wet grain loses quality and price."),
    ("Frost is expected tonight on your potato crop.", ["Give a light irrigation in the evening", "Harvest everything now", "Do nothing"], 0, "Moist soil holds warmth and protects against frost."),
    ("A long dry spell: soybean leaves are wilting.", ["Give a protective irrigation if you can", "Spray urea", "Plough the field"], 0, "One timely watering can save the crop."),
    ("Strong wind is forecast on the day you planned to spray.", ["Wait for a calm day to spray", "Spray anyway", "Spray double"], 0, "Spray drifts away in wind and harms people and other fields."),
    ("A hailstorm damaged your insured crop yesterday.", ["Report the loss within 72 hours", "Wait for next season", "Burn the field"], 0, "Late reports can lose the claim."),
    ("Hot and humid weather, and spots appear on tomato leaves.", ["Ask the KVK and check for blight", "Give more water", "Ignore it"], 0, "Blight spreads fast in humid weather. Early advice saves the crop."),
    ("Rain is expected in two days and fertiliser is due.", ["Apply after the rain", "Apply just before heavy rain", "Never apply"], 0, "Heavy rain washes fertiliser away."),
    ("The monsoon is two weeks late.", ["Choose short-duration varieties and ask the KVK", "Sow nothing this year", "Sow as usual on the same day"], 0, "Short-duration varieties finish before the rain ends."),
]

PESTS = {"foes": ["🐛", "🦗", "🐀", "🐌"], "friends": ["🐝", "🐞", "🪱", "🐸", "🦉"]}
PEST_LESSONS = ["Bees carry pollen and give you more fruit.", "Ladybird beetles eat aphids.", "Earthworms make the soil rich.", "Frogs and owls eat insects and rats."]
SEASONS = {"kharif": ["rice", "soybean", "maize", "cotton", "tur", "bajra", "groundnut", "urad", "kodo"], "rabi": ["wheat", "gram", "mustard", "lentil", "barley", "peas"]}
PAIRS = [("wheat", "atta"), ("gram", "besan"), ("mushroom", "dry_mushroom"), ("tomato", "tomato_puree"), ("mango", "amchur"), ("sugarcane", "jaggery"),
         ("mustard", "mustard_oil"), ("turmeric", "turmeric_powder")]
NAMEABLE = ["onion", "potato", "tomato", "garlic", "carrot", "banana", "mango", "maize", "groundnut", "brinjal", "lemon", "sunflower", "mushroom", "peas", "sugarcane", "orange"]

UI = [
    "Start", "Play again", "Next", "Your score", "Points", "Time", "Correct!", "Not quite.", "Well done!", "Game over", "Tap the answer, or tap the mic and say it.",
    "Say it", "Listening...", "Kharif", "Rabi", "Water", "Stop", "Soil moisture", "Too dry", "Too wet", "Just right", "Your guess (₹ per quintal)", "Check",
    "Today's mandi price", "Mandi A", "Mandi B", "Direct buyer", "Rate", "Commission", "Transport", "Money in hand", "Which gives the most money in hand?",
    "Which is the right total?", "Lives", "Tap now!", "Saved to your points.", "Sign in to save your points.", "Games", "Free games about farming. Play by touch or by voice.",
    "This week in your district", "Your best", "No games played yet.", "Play", "{n} points", "Friends of the farmer", "Pests", "Moves", "Pairs found",
    "Catch grain, dodge stones", "Say the name of this crop", "I heard: {text}", "Try again", "Rain", "Sun", "Scores", "Activity", "Performance",
    "How much you use Seedha Bazar in the last 30 days", "How well your farm does", "No mandi price is available for this crop today.",
]


def ui_strings() -> list:
    out = list(UI)
    for slug, emoji, title, line, cap, voice in GAMES:
        out += [title, line]
    for q, opts, _, why in QUIZ + WEATHER:
        out += [q, *opts, why]
    out += PEST_LESSONS
    return out


def data_for(slug: str, lang: str, state: str = "", district: str = "") -> dict:
    from web.i18n import tr

    T = lambda s: tr(lang, s)
    name = lambda k: tr(lang, catalog.name(k))
    if slug == "quiz":
        return {"items": [{"q": T(q), "opts": [T(o) for o in opts], "a": a, "why": T(why)} for q, opts, a, why in QUIZ]}
    if slug == "weather":
        return {"items": [{"q": T(q), "opts": [T(o) for o in opts], "a": a, "why": T(why)} for q, opts, a, why in WEATHER]}
    if slug == "season":
        return {"items": [{"crop": k, "name": name(k), "emoji": catalog.emoji(k), "season": s} for s, ks in SEASONS.items() for k in ks],
                "words": {"kharif": ["kharif", "खरीफ", "खरीप"], "rabi": ["rabi", "रबी", "रब्बी"]}}
    if slug == "memory":
        return {"pairs": [[{"k": a, "name": name(a), "emoji": catalog.emoji(a)}, {"k": b, "name": name(b), "emoji": catalog.emoji(b)}] for a, b in PAIRS]}
    if slug == "pests":
        return {**PESTS, "lessons": [T(x) for x in PEST_LESSONS]}
    if slug == "name":
        out = []
        for k in NAMEABLE:
            en, hi, mr, emoji, _ = catalog.PRODUCTS[k]
            out.append({"k": k, "emoji": emoji, "name": name(k), "say": list({en.split("(")[0].strip().lower(), hi, mr})})
        return {"items": out}
    if slug == "price":
        from rates import services as rate_services
        rows = rate_services.crop_prices(state, district)[:12]
        return {"items": [{"crop": r["crop"], "name": name(r["crop"]), "emoji": catalog.emoji(r["crop"]), "price": int(r["typical"])} for r in rows]}
    if slug in ("market", "sums"):
        from rates import services as rate_services
        rows = rate_services.crop_prices(state, district)[:8]
        return {"crops": [{"crop": r["crop"], "name": name(r["crop"]), "price": int(r["typical"])} for r in rows] or [{"crop": "wheat", "name": name("wheat"), "price": 2300}]}
    return {}
