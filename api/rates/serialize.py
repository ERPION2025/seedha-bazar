def _row(r: dict) -> dict:
    return {"market": r["market"], "district": r["district"], "state": r["state"], "date": r["date"].isoformat(),
            "min": int(r["min"]), "max": int(r["max"]), "modal": int(r["modal"])}


def quote_json(q: dict) -> dict:
    """A quote with plain numbers and ISO dates, for JSON responses."""
    msp = q["msp"]
    return {
        "crop": q["crop"], "label": q["label"], "state": q["state"], "district": q["district"], "scope": q["scope"],
        "typical": int(q["typical"]) if q["typical"] is not None else None,
        "as_of": q["as_of"].isoformat() if q["as_of"] else None, "markets_reporting": q["count"],
        "local": [_row(r) for r in q["local"]], "nearby": [_row(r) for r in q["nearby"]],
        "msp": {"price": int(msp["price"]), "season": msp["season"], "name": msp["name"]} if msp else None,
        "trend_pct": float(q["trend"]) if q["trend"] is not None else None, "sample_data": q["demo"],
        "unit": "INR per quintal", "source": "Agmarknet, Govt. of India (data.gov.in)",
    }
