"""Build the district boundary files the maps and the geofence use.

Input: geoBoundaries India ADM1 (states) and ADM2 (districts), simplified GeoJSON (ODbL 1.0; source: LGD via Pathways Data).
Output: web/static/web/geo/<state>.json (one FeatureCollection per state, coordinates rounded to ~100 m) and index.json.

    python tools/build_boundaries.py adm1.geojson adm2.geojson
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "web" / "geo"
ROUND = 3


def plain(name: str) -> str:
    """'Mahārāshtra' -> 'Maharashtra': the names the rest of the platform uses."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", plain(name).lower()).strip("-")


def rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    return geom["coordinates"]


def inside(pt, polygon) -> bool:
    x, y = pt
    ok = False
    for ring_i, ring in enumerate(polygon):
        j = len(ring) - 1
        hit = False
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
                hit = not hit
            j = i
        if ring_i == 0:
            ok = hit
        elif hit:
            return False
    return ok


def centroid(geom):
    pts = [p for poly in rings(geom) for p in poly[0]]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def bbox(geom):
    pts = [p for poly in rings(geom) for ring in poly for p in ring]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [round(min(xs), 3), round(min(ys), 3), round(max(xs), 3), round(max(ys), 3)]


def rounded(geom):
    def r(c):
        return [round(c[0], ROUND), round(c[1], ROUND)]

    def ring(rg):
        out = []
        for p in rg:
            q = r(p)
            if not out or q != out[-1]:
                out.append(q)
        return out if len(out) >= 4 else [r(p) for p in rg]

    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(rg) for rg in geom["coordinates"]]}
    return {"type": "MultiPolygon", "coordinates": [[ring(rg) for rg in poly] for poly in geom["coordinates"]]}


def main(adm1_path, adm2_path):
    states = json.load(open(adm1_path))["features"]
    districts = json.load(open(adm2_path))["features"]
    by_state = {s["properties"]["shapeName"]: [] for s in states}
    unplaced = []
    for d in districts:
        c = centroid(d["geometry"])
        # Vote with many of the district's own points: one centroid can land in a neighbour when shapes are simplified.
        # Border vertices sit on both states' edges, so vote with points strictly inside the district.
        b = bbox(d["geometry"])
        grid = [(b[0] + (b[2] - b[0]) * (i + 0.5) / 9, b[1] + (b[3] - b[1]) * (j + 0.5) / 9) for i in range(9) for j in range(9)]
        sample = [pt for pt in grid if any(inside(pt, poly) for poly in rings(d["geometry"]))] or [c]
        votes = {}
        for s in states:
            box = bbox(s["geometry"])
            hits = sum(1 for pt in sample if box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3] and any(inside(pt, poly) for poly in rings(s["geometry"])))
            if hits:
                votes[s["properties"]["shapeName"]] = hits
        home = max(votes, key=votes.get) if votes else None
        if home is None:  # centroid fell outside (odd shapes): use the state whose box holds it
            home = next((s["properties"]["shapeName"] for s in states if (lambda b: b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3])(bbox(s["geometry"]))), None)
        if home is None:
            unplaced.append(d["properties"]["shapeName"])
            continue
        by_state[home].append({"type": "Feature", "properties": {"district": plain(d["properties"]["shapeName"]), "state": plain(home), "c": [round(c[0], 3), round(c[1], 3)]},
                               "geometry": rounded(d["geometry"])})
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for s in states:
        name = s["properties"]["shapeName"]
        feats = by_state[name]
        if not feats:
            continue
        f = f"{slug(name)}.json"
        (OUT / f).write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
        index.append({"state": plain(name), "file": f, "bbox": bbox(s["geometry"]), "districts": sorted(x["properties"]["district"] for x in feats)})
    (OUT / "index.json").write_text(json.dumps({"source": "geoBoundaries IND ADM1/ADM2 (2021), ODbL 1.0, from LGD via Pathways Data", "states": index}, separators=(",", ":"), ensure_ascii=False))
    print(f"{sum(len(v) for v in by_state.values())} districts in {len(index)} states; not placed: {unplaced}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
