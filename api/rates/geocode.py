"""Latitude/longitude -> state and district, using OpenStreetMap's free Nominatim service.

Their usage policy: identify yourself, at most one request a second, and cache answers. We round to ~1 km squares and cache in the database,
so most requests never leave the server.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from decimal import Decimal

from django.conf import settings

from config.netutil import ssl_context

from .models import GeoCache

_lock = threading.Lock()
_last_call = [0.0]


class GeocodeError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _fetch(lat: str, lon: str) -> dict:
    q = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10, "addressdetails": 1, "accept-language": "en"})
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/reverse?{q}", headers={"User-Agent": settings.GEOCODER_USER_AGENT})
    with urllib.request.urlopen(req, timeout=10, context=ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reverse(lat: float, lon: float, fetch=_fetch) -> tuple[str, str]:
    """Returns (state, district) as OpenStreetMap names them. Raises GeocodeError('outside_india' | 'unavailable' | 'not_found')."""
    if not (6.0 <= lat <= 37.5 and 67.0 <= lon <= 98.0):
        raise GeocodeError("outside_india")
    la, lo = Decimal(str(round(lat, 2))), Decimal(str(round(lon, 2)))
    hit = GeoCache.objects.filter(lat=la, lon=lo).first()
    if hit:
        return hit.state, hit.district
    with _lock:  # one request a second, as the service asks
        wait = 1.1 - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        try:
            data = fetch(str(la), str(lo))
        except Exception:
            raise GeocodeError("unavailable")
        finally:
            _last_call[0] = time.monotonic()
    a = data.get("address") or {}
    if a.get("country_code") and a["country_code"] != "in":
        raise GeocodeError("outside_india")
    state = a.get("state", "")
    district = a.get("state_district") or a.get("county") or a.get("city") or ""
    if not state:
        raise GeocodeError("not_found")
    GeoCache.objects.get_or_create(lat=la, lon=lo, defaults={"state": state, "district": district})
    return state, district
