"""Daily mandi prices reported to Agmarknet (Govt. of India), served by data.gov.in as open data.

You need a free personal API key: sign in at https://data.gov.in, open "My Account" and generate one, then set DATA_GOV_IN_API_KEY.
(The shared demo key returns only 10 rows a call, so it is not enough.) Prices are rupees per quintal.
"""
import json
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator

from config.netutil import ssl_context

from .base import parse_date, to_price

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
PAGE = 1000
MAX_PAGES = 60  # a safety stop: 60,000 rows is far more than one day holds


def http_get_json(url: str, timeout: int = 40) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SeedhaBazar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url, retries=3, http=http_get_json):
    for attempt in range(retries):
        try:
            return http(url)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def normalise(record: dict) -> dict | None:
    """The API has used both snake_case and Capitalised field names over time, so keys are matched without case."""
    r = {k.lower().replace("_x0020_", "_"): v for k, v in record.items()}
    day = parse_date(r.get("arrival_date"))
    modal = to_price(r.get("modal_price"))
    if day is None or modal is None or not r.get("market") or not r.get("commodity"):
        return None
    low, high = to_price(r.get("min_price")) or modal, to_price(r.get("max_price")) or modal
    return {
        "date": day, "state": str(r.get("state", "")).strip(), "district": str(r.get("district", "")).strip(),
        "market": str(r["market"]).strip(), "commodity": str(r["commodity"]).strip(),
        "variety": str(r.get("variety", "") or "").strip(), "grade": str(r.get("grade", "") or "").strip(),
        "min_price": min(low, modal), "max_price": max(high, modal), "modal_price": modal,
    }


class DataGovInSource:
    name = "agmarknet"

    def __init__(self, api_key: str, states: list[str] | None = None, http=http_get_json):
        self.api_key, self.states, self.http = api_key, states or [], http

    def _pages(self, extra: dict) -> Iterator[dict]:
        offset = 0
        for _ in range(MAX_PAGES):
            q = {"api-key": self.api_key, "format": "json", "limit": PAGE, "offset": offset, **extra}
            body = _get(f"{URL}?{urllib.parse.urlencode(q)}", http=self.http)
            records = body.get("records") or []
            yield from records
            offset += len(records)
            if len(records) < PAGE or offset >= int(body.get("total") or 0):
                return

    def fetch(self) -> Iterator[dict]:
        scopes = [{"filters[state]": s} for s in self.states] or [{}]
        for extra in scopes:
            for record in self._pages(extra):
                row = normalise(record)
                if row:
                    yield row
