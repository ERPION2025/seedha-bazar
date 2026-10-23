"""Forecasts for each farmer's village, crop-stage advice, and the daily alert run.

Forecast source: Open-Meteo (free for non-commercial use; commercial use needs their paid API key, set WEATHER_API_KEY).
Village location: OpenStreetMap search once per village (rate-limited), else the district's centre.
"""
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from config.netutil import ssl_context
from extension import geo

from . import rules, stages
from .models import Alert, Forecast, Place

log = logging.getLogger("seedha.weather")
FRESH_HOURS = 3
_last_osm = [0.0]


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": getattr(settings, "GEOCODER_USER_AGENT", "SeedhaBazar/1.0")})
    with urllib.request.urlopen(req, timeout=20, context=ssl_context()) as r:  # noqa: S310 - fixed https services
        return json.loads(r.read(2_000_000))


def district_centre(state: str, district: str):
    name = geo.official_name(state, district)
    f = geo.state_file(state)
    if not f:
        return None
    for feat in geo.state_features(f):
        if feat["properties"]["district"] == name or geo.same_district(feat["properties"]["district"], district):
            lon, lat = feat["properties"]["c"]
            return lat, lon
    return None


def place_for(state: str, district: str, village: str = "", lookup: bool = True) -> Place | None:
    village = (village or "").strip()
    p = Place.objects.filter(state=state, district=district, village=village).first()
    if p:
        return p
    found = None
    if village and lookup and getattr(settings, "WEATHER_LOOKUP_VILLAGES", True):
        wait = 1.1 - (time.monotonic() - _last_osm[0])  # OpenStreetMap allows one request a second
        if wait > 0:
            time.sleep(wait)
        _last_osm[0] = time.monotonic()
        try:
            q = urllib.parse.urlencode({"format": "json", "limit": 1, "countrycodes": "in", "q": f"{village}, {district}, {state}"})
            rows = _get(f"https://nominatim.openstreetmap.org/search?{q}")
            if rows:
                lat, lon = float(rows[0]["lat"]), float(rows[0]["lon"])
                where = geo.district_at(lat, lon)
                if where and geo.same_district(where[1], district):  # only trust a hit inside the right district
                    found = (lat, lon, "osm")
        except Exception as e:
            log.info("village lookup failed for %s: %s", village, e)
    if found is None:
        c = district_centre(state, district)
        if c is None:
            return None
        found = (c[0], c[1], "district")
    p, _ = Place.objects.get_or_create(state=state, district=district, village=village, defaults={"lat": found[0], "lon": found[1], "source": found[2]})
    return p


def _round(x):
    return round(x * 20) / 20  # about 5 km


def forecast(lat: float, lon: float, fetch: bool = True) -> list[dict] | None:
    lat, lon = _round(lat), _round(lon)
    f = Forecast.objects.filter(lat=lat, lon=lon).order_by("-fetched_at").first()
    if f and timezone.now() - f.fetched_at < timedelta(hours=FRESH_HOURS):
        return f.days
    if not fetch:
        return f.days if f else None
    fields = "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,relative_humidity_2m_mean,weather_code"
    key = getattr(settings, "WEATHER_API_KEY", "")
    base = "https://customer-api.open-meteo.com/v1/forecast" if key else "https://api.open-meteo.com/v1/forecast"
    url = f"{base}?latitude={lat}&longitude={lon}&daily={fields}&timezone=Asia%2FKolkata&forecast_days=7" + (f"&apikey={key}" if key else "")
    try:
        d = _get(url)["daily"]
    except Exception as e:
        log.warning("forecast failed for %s,%s: %s", lat, lon, e)
        return f.days if f else None
    days = [{"date": d["time"][i], "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i], "rain_mm": d["precipitation_sum"][i],
             "rain_prob": d["precipitation_probability_max"][i], "wind": d["wind_speed_10m_max"][i], "gust": d["wind_gusts_10m_max"][i],
             "humidity": d["relative_humidity_2m_mean"][i], "code": d["weather_code"][i]} for i in range(len(d["time"]))]
    Forecast.objects.create(lat=lat, lon=lon, days=days)
    Forecast.objects.filter(lat=lat, lon=lon, fetched_at__lt=timezone.now() - timedelta(days=2)).delete()
    return days


def crop_rows(user, today=None):
    """Each active (or stored) crop of a farmer with its stage."""
    from farmerbook.models import CropCycle
    from farmerbook.serializers import stock_kg

    today = today or timezone.localdate()
    out = []
    for c in CropCycle.objects.filter(owner=user, deleted_at__isnull=True).exclude(status="closed").select_related("plot"):
        st = stages.stage_of(c, today, in_stock=c.status == "harvested" and stock_kg(c) > 0)
        if st:
            out.append({"cycle": c, "crop": c.crop, "stage": st, "stage_label": stages.LABELS.get(st, st)})
    return out


def alerts_for(user, days: list[dict], today=None) -> list[dict]:
    out = []
    for row in crop_rows(user, today):
        for a in rules.advise(row["crop"], row["stage"], days, row["cycle"].season):
            out.append({**a, **row})
    return out


def run_daily(today=None, send: bool = True) -> dict:
    """Once a day: forecast for each farmer's village, alerts for their crops, one message per farmer with the most urgent advice."""
    from accounts.models import UserStatus
    from notify import service as notify
    from profiles.models import FarmerProfile
    from web.i18n import tr
    import catalog

    today = today or timezone.localdate()
    farmers = FarmerProfile.objects.filter(user__status=UserStatus.ACTIVE).exclude(district="").select_related("user")
    made = sent = 0
    for fp in farmers:
        p = place_for(fp.state, fp.district, fp.village)
        days = forecast(p.lat, p.lon) if p else None
        if not days:
            continue
        new = []
        for a in alerts_for(fp.user, days, today):
            obj, created = Alert.objects.get_or_create(farmer=fp.user, crop=a["crop"], kind=a["kind"], day=date.fromisoformat(a["day"]),
                                                       defaults={"crop_cycle": a["cycle"], "stage": a["stage"], "advice": a["advice"], "value": a["value"],
                                                                 "state": fp.state, "district": fp.district})
            if created:
                made += 1
                new.append(obj)
        if send and new:
            u = fp.user
            first = sorted(new, key=lambda x: (x.day, ["frost", "rain", "wind", "heat", "disease", "dry"].index(x.kind)))[0]
            notify.send("sms", u.phone, "weather_alert", u.language, user=u, related=f"weather:{first.pk}",
                        crop=tr(u.language, catalog.name(first.crop)), date=first.day.strftime("%d %b"), advice=tr(u.language, first.advice),
                        link=f"{settings.SITE_URL}/weather/")
            Alert.objects.filter(pk__in=[x.pk for x in new]).update(sent_at=timezone.now())
            sent += 1
    return {"alerts": made, "messages": sent}


def due(now=None) -> bool:
    """Run once a day, after 6 a.m. India time."""
    from .models import Run

    now = timezone.localtime(now or timezone.now())
    return now.hour >= 6 and not Run.objects.filter(day=now.date()).exists()


def tick(now=None) -> dict | None:
    from .models import Run

    if not due(now):
        return None
    out = run_daily()
    Run.objects.get_or_create(day=timezone.localtime(now or timezone.now()).date(), defaults={"result": out})
    return out
