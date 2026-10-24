"""The WDRA public list of registered warehouses (wdra.gov.in/registered-wh-public), read state by state and kept fresh.

The list is a form: pick a state, submit, and the page shows every registered warehouse there (manager, name, WDRA id,
address, district, capacity, registration and validity dates, contact, status, remark). WDRA's robots.txt allows reading it.
We read one state at a time, a few states per run with a pause between them, so the whole country is refreshed about weekly.
A warehouse that drops off WDRA's list is marked "Not listed", never deleted (farmers' records may point to it).
"""
import html
import http.cookiejar
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from config.netutil import ssl_context

from .models import Warehouse, WarehouseSync

log = logging.getLogger("seedha.storage")
NS = "_in_gov_wdra_warehouse_publiclist_portlet_WarehousePubliclistPortlet_INSTANCE_faio_"
UA = "SeedhaBazar/1.0 (+https://seedhabazar.in; warehouse list for farmers)"
COLUMNS = ["operator", "name", "wdra_id", "address", "district", "state", "capacity", "registered", "valid", "phone", "status", "remarks"]


class Session:
    """A cookie-keeping browser for the form's session token (p_auth)."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), urllib.request.HTTPSHandler(context=ssl_context()))

    def get(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with self.opener.open(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")

    def post(self, url: str, data: dict) -> str:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
        with self.opener.open(req, timeout=180) as r:
            return r.read().decode("utf-8", "replace")


def states_and_action(page: str) -> tuple[dict, str]:
    """{state name: WDRA code} from the form's list, and the form's address (with its p_auth token)."""
    i = page.find(f'{NS}selectStateName" name')
    opts = re.findall(r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*<', page[i:i + 8000]) if i >= 0 else []
    m = re.search(r'<form action="(https://wdra\.gov\.in/registered-wh-public[^"]*p_auth=[^"]*)"', page)
    return {name.strip(): code for code, name in opts}, html.unescape(m.group(1)) if m else ""


def parse_table(page: str) -> list[dict]:
    i = page.find('id="resultTableId"')
    if i < 0:
        return []
    body = page[i:page.find("</table>", i)]
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", body, re.S):
        cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) >= len(COLUMNS):
            out.append(dict(zip(COLUMNS, cells)))
    return out


def _date(s: str):
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _capacity(s: str):
    try:
        return Decimal(s.replace(",", "").strip()).quantize(Decimal("0.1"))
    except (InvalidOperation, ValueError):
        return None


def _state_name(s: str) -> str:
    """WDRA writes 'Jammu And Kashmir'; we write 'Jammu and Kashmir'."""
    return " ".join(w if w.lower() not in ("and", "of", "the") or k == 0 else w.lower() for k, w in enumerate(s.split()))


@transaction.atomic
def save_state(state: str, rows: list[dict]) -> dict:
    now = timezone.now()
    added = updated = 0
    seen = set()
    for r in rows:
        wid = r["wdra_id"].strip()
        if not wid or wid in seen:
            continue
        seen.add(wid)
        status = r["status"].strip()[:30]
        fields = {"name": r["name"][:200], "operator": r["operator"][:200], "address": r["address"][:300], "district": r["district"].strip().title()[:80],
                  "state": _state_name(r["state"] or state)[:60], "capacity_mt": _capacity(r["capacity"]), "registered_on": _date(r["registered"]),
                  "valid_until": _date(r["valid"]), "phone": r["phone"][:40], "wdra_status": status, "remarks": r["remarks"][:200],
                  "verified": status.lower() == "active", "source": "wdra", "last_seen_at": now}
        _, created = Warehouse.objects.update_or_create(wdra_reg_no=wid, defaults=fields)
        added += created
        updated += not created
    gone = 0
    if seen:  # only after a good read: anything WDRA no longer lists for this state
        gone = (Warehouse.objects.filter(source="wdra", state__iexact=_state_name(state)).exclude(wdra_reg_no__in=seen).exclude(wdra_status="Not listed")
                .update(wdra_status="Not listed", verified=False))
    return {"rows": len(rows), "added": added, "updated": updated, "gone": gone}


def sync_states(names: list[str] | None = None, limit: int | None = None, pause: float = 3.0, session: Session | None = None) -> list[WarehouseSync]:
    """Read these states (default: the ones most overdue). Each state gets its own record, good or bad."""
    s = session or Session()
    page = s.get(settings.WDRA_LIST_URL)
    codes, action = states_and_action(page)
    if not codes or not action:
        raise RuntimeError("The WDRA page has changed: no state list or form found.")
    wanted = names or due_states(codes, limit=limit or settings.WDRA_STATES_PER_RUN)
    runs = []
    for k, name in enumerate(wanted):
        code = codes.get(name) or next((c for n, c in codes.items() if n.lower() == name.lower()), None)
        if not code or code == "-1":
            continue
        run = WarehouseSync.objects.create(state=_state_name(name), state_code=code)
        try:
            if k:
                time.sleep(pause)
            res = s.post(action, {f"{NS}formDate": str(int(time.time() * 1000)), f"{NS}selectStateName": code, f"{NS}GoButton": ""})
            rows = parse_table(res)
            if not rows and "resultTableId" not in res:
                raise RuntimeError("No result table in WDRA's answer.")
            out = save_state(name, rows)
            run.ok, run.rows, run.added, run.updated, run.gone = True, out["rows"], out["added"], out["updated"], out["gone"]
            page = res  # the answer carries a fresh form token for the next state
            codes2, action2 = states_and_action(res)
            action = action2 or action
        except Exception as e:
            log.warning("WDRA %s failed: %s", name, e)
            run.error = f"{type(e).__name__}: {e}"[:300]
        run.finished_at = timezone.now()
        run.save()
        runs.append(run)
    return runs


def due_states(codes: dict, limit: int, now=None) -> list[str]:
    """States never read, then those read longest ago; skipping any read well within WDRA_REFRESH_DAYS."""
    now = now or timezone.now()
    fresh_after = now - timedelta(days=settings.WDRA_REFRESH_DAYS)
    last = {}
    for r in WarehouseSync.objects.filter(ok=True).order_by("started_at"):
        last[r.state.lower()] = r.started_at
    names = [n for n, c in codes.items() if c != "-1"]
    pending = [n for n in names if last.get(_state_name(n).lower(), fresh_after - timedelta(seconds=1)) < fresh_after]
    pending.sort(key=lambda n: last.get(_state_name(n).lower(), now - timedelta(days=3650)))
    return pending[:limit]


def due(now=None) -> bool:
    """Once a day at most (a failed run retries after an hour)."""
    now = now or timezone.now()
    last = WarehouseSync.objects.first()
    if last is None:
        return True
    if not last.ok:
        return now - last.started_at >= timedelta(hours=1)
    return now - last.started_at >= timedelta(hours=23)


def tick(now=None) -> int | None:
    if not settings.WDRA_ENABLED or not due(now):
        return None
    return sum(r.ok for r in sync_states())


def status() -> list[dict]:
    """Per state: warehouses we hold, active ones, and the last read. For the console."""
    from django.db.models import Count, Q, Sum

    counts = {r["state"].lower(): r for r in Warehouse.objects.filter(source="wdra").values("state")
              .annotate(n=Count("id"), active=Count("id", filter=Q(wdra_status__iexact="Active")), cap=Sum("capacity_mt", filter=Q(wdra_status__iexact="Active")))}
    last = {}
    for r in WarehouseSync.objects.order_by("started_at"):
        last[r.state.lower()] = r
    names = sorted(set(list(last) + list(counts)))
    out = []
    for k in names:
        c, r = counts.get(k, {}), last.get(k)
        out.append({"state": (r.state if r else c.get("state", k)), "n": c.get("n", 0), "active": c.get("active", 0), "cap": c.get("cap") or 0, "last": r})
    return out
