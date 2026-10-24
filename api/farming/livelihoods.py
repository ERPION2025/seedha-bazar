"""The livelihoods Seedha Bazar supports, and everything that differs between them, in one place.

A farmer, FPO or NGO picks its livelihoods when it starts. Menus, forms, listings and filters then show only what fits:
a silk farmer never sees fish ponds, a dairy farmer never sees mandi crop tools. Every livelihood uses the same few
building blocks (a farm unit, quick daily entries, reminders, sales into the marketplace, one profit and loss), so a new
one is a new entry here, not new code.

Reminders are general good practice only. They never give medicine doses: they say "with your vet" or "with the
department", and disease signs go to an expert through Ask an expert.
"""

CROPS = "crops"

LIVELIHOODS = {
    "crops": {"label": "Crops", "emoji": "🌾", "hint": "Grains, pulses, vegetables, fruit"},
    "dairy": {
        "label": "Dairy", "emoji": "🐄", "hint": "Cows, buffaloes, goats",
        "kinds": [("cow", "Cows"), ("buffalo", "Buffaloes"), ("goat", "Goats")],
        "count": "Animals", "tag": "Ear tag numbers (optional)", "produce": ("milk", "litre", "Milk"),
        "products": {"milk": ["litre"], "ghee": ["kg"], "paneer": ["kg"]},
        "schedule": [(0, 90, "Deworming due. Ask your vet or para-vet."), (0, 180, "Foot-and-mouth (FMD) vaccination due. Contact the animal husbandry department."),
                     (0, 365, "HS and BQ vaccination before the monsoon. Contact the animal husbandry department.")],
    },
    "poultry": {
        "label": "Poultry", "emoji": "🐔", "hint": "Broilers, layers, desi birds",
        "kinds": [("broiler", "Broiler batch"), ("layer", "Layer flock"), ("desi", "Desi birds")],
        "count": "Birds", "tag": "", "produce": ("eggs", "tray", "Eggs (trays of 30)"),
        "products": {"eggs": ["tray"], "broiler": ["kg"], "desi_chicken": ["kg", "piece"]},
        "schedule": [(5, None, "Ranikhet (ND) vaccine due for the chicks. Check the schedule with your vet."), (14, None, "Gumboro (IBD) vaccine due. Check with your vet."),
                     (21, None, "Ranikhet booster due. Check with your vet."), (35, None, "Weigh a few birds and plan the sale."),
                     (0, 7, "Clean waterers and check litter; keep visitors out of the shed.")],
    },
    "fisheries": {
        "label": "Fisheries", "emoji": "🐟", "hint": "Ponds, tanks, cages",
        "kinds": [("pond", "Pond"), ("tank", "Tank"), ("cage", "Cage")],
        "count": "Fish seed stocked", "area": "Water area (acres)", "tag": "Fisheries licence or registration (optional)", "produce": ("fish", "kg", "Fish harvested"),
        "products": {"fish": ["kg", "quintal"]},
        "schedule": [(0, 15, "Net a few fish, check their growth and the water colour."), (240, None, "Plan the harvest and talk to buyers.")],
    },
    "apiculture": {
        "label": "Beekeeping", "emoji": "🐝", "hint": "Bee boxes, honey",
        "kinds": [("apiary", "Apiary")],
        "count": "Bee boxes", "tag": "Madhukranti registration number (optional)", "produce": ("honey", "kg", "Honey extracted"),
        "products": {"honey": ["kg"], "beeswax": ["kg"]},
        "schedule": [(0, 7, "Inspect the boxes: queen, brood, food and pests (mites, wax moth)."), (0, 30, "Note where the bees are and what is flowering nearby.")],
    },
    "sericulture": {
        "label": "Sericulture", "emoji": "🐛", "hint": "Mulberry, tasar, eri silk",
        "kinds": [("mulberry", "Mulberry silk"), ("tasar", "Tasar silk"), ("eri", "Eri silk")],
        "count": "Disease-free layings (DFLs)", "area": "Food plants (acres)", "tag": "", "produce": ("cocoons", "kg", "Cocoons harvested"),
        "products": {"cocoons": ["kg"], "silk_yarn": ["kg"]},
        "schedule": [(-2, None, "Clean and disinfect the rearing house and trays before the worms arrive."), (0, None, "Brush the young worms (chawki) onto fresh, tender leaves."),
                     (24, None, "Worms are ripening: set out the mountages."), (30, None, "Harvest the cocoons and plan the sale.")],
    },
    "piggery": {
        "label": "Piggery", "emoji": "🐖", "hint": "Breeding and fattening pigs",
        "kinds": [("breeding", "Breeding unit"), ("fattening", "Fattening unit")],
        "count": "Pigs", "tag": "Ear tag numbers (optional)", "produce": ("piglets", "piece", "Piglets born"),
        "products": {"pigs": ["kg"], "piglets": ["piece"]},
        "schedule": [(0, None, "Keep new pigs apart for 2 weeks, and keep a visitor and disinfection register."),
                     (0, 180, "Classical swine fever (CSF) vaccine booster due. Ask your vet."), (0, 90, "Deworming due. Ask your vet.")],
    },
}
CODES = list(LIVELIHOODS)
ANIMAL_CODES = [c for c in CODES if c != CROPS]
CHOICES = [(c, v["label"]) for c, v in LIVELIHOODS.items()]

# What each part of the app is for. Not listed = for everyone.
CROP_ONLY = {"/farmer/book/", "/inputs/", "/farmer/groups/", "/fpo/groups/", "/farmer/pools/", "/fpo/pools/", "/storage/", "/insurance/", "/fpo/insurance/",
             "/value/", "/rates/", "/calculator/"}
ANIMAL_ONLY = {"/farm/", "/fpo/farm/"}


def of(obj) -> list[str]:
    """The livelihoods of a user, farmer profile or organisation. Older accounts that never chose are treated as crop farmers."""
    if obj is None:
        return [CROPS]
    if getattr(obj, "role", "") == "farmer":
        obj = obj.farmer_profile
    elif getattr(obj, "role", "") == "agent":
        from profiles.models import OrgMembership
        m = OrgMembership.objects.filter(user=obj).select_related("organisation").first()
        obj = m.organisation if m else None
        if obj is None:
            return [CROPS]
    return list(getattr(obj, "segments", None) or [CROPS])


def chosen(obj) -> bool:
    if getattr(obj, "role", "") == "farmer":
        obj = obj.farmer_profile
    return bool(getattr(obj, "segments", None))


def menu_allows(url: str, segs: list[str]) -> bool:
    if url in CROP_ONLY:
        return CROPS in segs
    if url in ANIMAL_ONLY:
        return any(s in ANIMAL_CODES for s in segs)
    return True


def products_of(segs) -> list[str]:
    return [p for s in segs for p in LIVELIHOODS.get(s, {}).get("products", {})]


def livelihood_of_product(product: str) -> str:
    for code, cfg in LIVELIHOODS.items():
        if product in cfg.get("products", {}):
            return code
    return CROPS


def units_for(product: str) -> list[str]:
    for cfg in LIVELIHOODS.values():
        if product in cfg.get("products", {}):
            return cfg["products"][product]
    return []
