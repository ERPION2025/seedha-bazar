"""IMD district weather warnings (India Meteorological Department), for the next five days.

IMD's APIs answer only servers whose IP address IMD has whitelisted ("IP ... needs to be whitelisted"). To switch this on:
write to IMD (the API page on mausam.imd.gov.in names the contact), give our server's fixed public IP, and when IMD confirms,
set IMD_API_ENABLED=1. Until then this module does nothing, and weather comes from Open-Meteo.

IMD's District AAS (agromet advisory) bulletins on imdagrimet.gov.in sit behind a captcha, so they are not read automatically;
KVKs that receive them can publish the advice for their districts in Institution Connect.

The warning and colour codes below follow IMD's API document; check them against the copy IMD sends with the access.
"""
import json
import logging
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from config.netutil import ssl_context

from .models import FeedRun
from .services import save_feed_item

log = logging.getLogger("seedha.advisory")

WARNINGS = {"2": "Heavy rain", "3": "Heavy snow", "4": "Thunderstorm and lightning, squall", "5": "Hailstorm", "6": "Dust storm", "7": "Dust raising winds",
            "8": "Strong surface winds", "9": "Heat wave", "10": "Hot day", "11": "Warm night", "12": "Cold wave", "13": "Cold day", "14": "Ground frost", "15": "Fog",
            "16": "Very heavy rain", "17": "Extremely heavy rain"}
COLOUR = {"1": "critical", "2": "warning", "3": "info"}  # red: take action, orange: be prepared, yellow: be updated; green (4): nothing to say


def fetch() -> list[dict]:
    req = urllib.request.Request(settings.IMD_WARNINGS_URL, headers={"User-Agent": "SeedhaBazar/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return data if isinstance(data, list) else data.get("data", [])


def parse(rows: list[dict]) -> list[dict]:
    from extension import geo

    out = []
    today = timezone.localdate()
    for r in rows:
        district = (r.get("District") or r.get("district") or "").strip().title()
        n = geo.norm(district)
        states = [st for st in geo.states() if any(geo.norm(d) == n for d in geo.districts_of(st))] if district else []
        if not district or len(states) != 1:
            continue
        for day in range(1, 6):
            codes = [c.strip() for c in str(r.get(f"Day_{day}") or "").split(",") if c.strip() and c.strip() != "1"]
            sev = COLOUR.get(str(r.get(f"Day{day}_Color") or "").strip())
            if not codes or not sev:
                continue
            when = today + timedelta(days=day - 1)
            text = ", ".join(WARNINGS.get(c, c) for c in codes)
            out.append({"state": states[0], "district": district, "date": when, "severity": sev, "text": text})
    return out


def sync(rows: list[dict] | None = None) -> dict:
    run = FeedRun.objects.create(feed="imd")
    try:
        items = parse(rows if rows is not None else fetch())
        saved = 0
        for it in items:
            key = f"imd:{it['district']}:{it['date']:%Y%m%d}:{it['text']}"[:80]
            a, created = save_feed_item("imd", key, f"IMD {it['date']:%d %b}: {it['text']}.", timezone.now(), state=it["state"], district=it["district"],
                                        issuer="IMD", severity=it["severity"], kind="weather", valid_until=it["date"], url="https://mausam.imd.gov.in/")
            if created:
                saved += 1
                if it["severity"] in ("critical", "warning"):
                    from .services import notify_district
                    notify_district(a, cap=300)
        run.ok, run.fetched, run.saved = True, len(items), saved
    except Exception as e:
        log.warning("IMD warnings failed: %s", e)
        run.error = f"{type(e).__name__}: {e}"[:300]
    run.finished_at = timezone.now()
    run.save()
    return {"ok": run.ok, "fetched": run.fetched, "saved": run.saved}
