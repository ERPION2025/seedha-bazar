"""National rules and how the catalog's crops fall into insurance groups.

Under PMFBY (and RWBCIS) the farmer's premium is capped: 2% of the sum insured for kharif food grains and oilseeds,
1.5% for rabi food grains and oilseeds, and 5% for annual commercial and horticulture crops. Government pays the rest.
These caps are the same in every state; what states notify is which crops and areas are covered, the sum insured, the
cut-off dates and the insurance company. Those come in as state Plan rows (see `load_insurance_plans`).
"""
from decimal import Decimal

import catalog

NATIONAL = [
    # scheme, season, group, farmer share %
    ("pmfby", "kharif", "food", Decimal("2")),
    ("pmfby", "rabi", "food", Decimal("1.5")),
    ("pmfby", "annual", "commercial", Decimal("5")),
    ("rwbcis", "kharif", "food", Decimal("2")),
    ("rwbcis", "rabi", "food", Decimal("1.5")),
    ("rwbcis", "annual", "commercial", Decimal("5")),
]
COMMERCIAL_RAW = {"cotton", "sugarcane", "turmeric", "red_chilli", "coriander"}
RISKS = {
    "pmfby": "Yield loss from drought, dry spell, flood, inundation, pests and disease, landslide, fire, lightning, storm, hail and cyclone. Also prevented sowing, mid-season adversity, localised calamities and post-harvest loss (up to 14 days in the field).",
    "rwbcis": "Pays out on weather readings (rain, temperature, humidity, wind) at the reference weather station, not on a crop-cutting survey.",
}
HECTARE_PER_ACRE = Decimal("0.404686")


def group_of(crop: str) -> str:
    if catalog.kind(crop) == catalog.FRESH or crop in COMMERCIAL_RAW:
        return "commercial"
    return "food"


def season_for(crop: str, season: str) -> str:
    """Commercial and horticulture crops are insured as annual crops; food crops by their sowing season."""
    if group_of(crop) == "commercial":
        return "annual"
    return season if season in ("kharif", "rabi") else "kharif"
