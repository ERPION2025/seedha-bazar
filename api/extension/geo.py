"""Geofence: which district a point is in, and matching district names written different ways.

Uses the boundary files in web/static/web/geo (geoBoundaries, ODbL, from LGD), loaded once per state when first needed.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

GEO = Path(__file__).resolve().parents[1] / "web" / "static" / "web" / "geo"


@lru_cache(maxsize=1)
def index() -> dict:
    try:
        return json.loads((GEO / "index.json").read_text())
    except FileNotFoundError:
        return {"states": []}


@lru_cache(maxsize=40)
def state_features(file: str) -> list:
    return json.loads((GEO / file).read_text())["features"]


def _rings(geom):
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def _inside(x, y, polygon) -> bool:
    ok = False
    for k, ring in enumerate(polygon):
        hit, j = False, len(ring) - 1
        for i in range(len(ring)):
            xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
                hit = not hit
            j = i
        if k == 0:
            ok = hit
        elif hit:
            return False
    return ok


def district_at(lat: float, lon: float) -> tuple[str, str] | None:
    """(state, district) for a point, or None outside India."""
    for st in index()["states"]:
        b = st["bbox"]
        if not (b[0] <= lon <= b[2] and b[1] <= lat <= b[3]):
            continue
        for f in state_features(st["file"]):
            if any(_inside(lon, lat, poly) for poly in _rings(f["geometry"])):
                return f["properties"]["state"], f["properties"]["district"]
    return None


def norm(name: str) -> str:
    n = re.sub(r"\(.*?\)", " ", (name or "").lower())
    return re.sub(r"[^a-z]+", "", n)


ALIASES = {"hoshangabad": "narmadapuram", "narsinghpur": "narsimhapur", "agarmalwa": "agar"}


def same_district(a: str, b: str) -> bool:
    x, y = norm(a), norm(b)
    x, y = ALIASES.get(x, x), ALIASES.get(y, y)
    return bool(x) and (x == y or x.startswith(y) or y.startswith(x))


def state_file(state: str) -> str:
    for st in index()["states"]:
        if st["state"].lower() == (state or "").lower():
            return st["file"]
    return ""


def official_name(state: str, district: str) -> str:
    """The boundary file's spelling of a district, so the map can outline it."""
    for st in index()["states"]:
        if st["state"].lower() == (state or "").lower():
            for d in st["districts"]:
                if same_district(d, district):
                    return d
    return district


def states() -> list[str]:
    return [st["state"] for st in index()["states"]]


def districts_of(state: str) -> list[str]:
    for st in index()["states"]:
        if st["state"].lower() == (state or "").lower():
            return st["districts"]
    return []


def states_with_district(district: str) -> list[str]:
    return [st["state"] for st in index()["states"] if any(same_district(d, district) for d in st["districts"])]


def check_place(state: str, district: str) -> tuple[bool, str]:
    """(ok, suggested_state). ok is True when the district is in the state, or when we cannot tell (no boundary data)."""
    if not index()["states"] or not district:
        return True, ""
    if any(same_district(d, district) for d in districts_of(state)):
        return True, ""
    homes = states_with_district(district)
    return False, homes[0] if len(homes) == 1 else ""
