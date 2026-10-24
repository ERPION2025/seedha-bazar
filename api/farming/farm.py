"""Farm units beyond crops: what is due, what was produced and earned, and the whole-farm picture across livelihoods."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from .livelihoods import CROPS, LIVELIHOODS
from .models import FarmEntry, FarmUnit

D = Decimal
WINDOW_BACK, WINDOW_AHEAD = 14, 7


def due_tasks(unit: FarmUnit, today=None) -> list[dict]:
    """Reminders from the livelihood's schedule that fall due from two weeks ago to a week ahead and are not marked done."""
    today = today or timezone.localdate()
    if not unit.active:
        return []
    done = set(FarmEntry.objects.filter(unit=unit, kind="task").values_list("ref", flat=True))
    out = []
    for i, (start, every, text) in enumerate(LIVELIHOODS.get(unit.livelihood, {}).get("schedule", [])):
        first = unit.started_on + timedelta(days=start)
        if every and today > first:
            k = (today - first).days // every
            when = first + timedelta(days=k * every)
            if f"{i}:{when}" in done or (today - when).days > WINDOW_BACK:
                when += timedelta(days=every)
        else:
            when = first
        ref = f"{i}:{when}"
        if ref in done or not (-WINDOW_BACK <= (when - today).days <= WINDOW_AHEAD):
            continue
        days = (when - today).days
        out.append({"unit": unit, "ref": ref, "date": when, "text": text, "days": days, "late": max(0, -days)})
    return out


def tasks_for(user, today=None) -> list[dict]:
    rows = [t for u in FarmUnit.objects.filter(owner=user, active=True) for t in due_tasks(u, today)]
    return sorted(rows, key=lambda t: t["date"])


def head_count(unit: FarmUnit) -> int:
    agg = unit.entries.filter(kind__in=["added", "loss", "sale"]).values("kind").annotate(q=Sum("quantity"))
    by = {r["kind"]: r["q"] or 0 for r in agg}
    if unit.livelihood in ("dairy", "piggery", "poultry"):
        return max(0, int(unit.count + by.get("added", 0) - by.get("loss", 0)))
    return unit.count


def summary(unit: FarmUnit, days: int = 30) -> dict:
    since = timezone.localdate() - timedelta(days=days)
    e = unit.entries.filter(date__gte=since)
    money = unit.entries.aggregate(inc=Sum("amount", filter=Q(kind="sale")), exp=Sum("amount", filter=Q(kind__in=FarmEntry.MONEY_OUT)))
    return {"produced": e.filter(kind="produce").aggregate(t=Sum("quantity"))["t"] or D(0), "lost": e.filter(kind="loss").aggregate(t=Sum("quantity"))["t"] or D(0),
            "income": money["inc"] or D(0), "expenses": money["exp"] or D(0), "head": head_count(unit)}


def money(user, start=None, end=None) -> list[dict]:
    """Income and costs per unit, for the profit and loss, the income statement and the whole-farm view."""
    qs = FarmEntry.objects.filter(owner=user)
    if start and end:
        qs = qs.filter(date__range=(start, end))
    rows = defaultdict(lambda: {"income": D(0), "expenses": D(0), "by": defaultdict(D)})
    for e in qs.exclude(amount__isnull=True).select_related("unit"):
        r = rows[e.unit]
        if e.kind == "sale":
            r["income"] += e.amount
        elif e.kind in FarmEntry.MONEY_OUT:
            r["expenses"] += e.amount
            r["by"][e.get_kind_display()] += e.amount
    return [{"unit": u, "livelihood": u.livelihood, "income": v["income"], "expenses": v["expenses"], "net": v["income"] - v["expenses"], "by": dict(v["by"])}
            for u, v in rows.items()]


def whole_farm(user, days: int = 365) -> list[dict]:
    """Integrated farming: earnings and costs per livelihood over the last year, crops included."""
    from farmerbook.models import Expense, Sale

    end = timezone.localdate()
    start = end - timedelta(days=days)
    out = defaultdict(lambda: {"income": D(0), "expenses": D(0)})
    out[CROPS]["income"] = Sale.objects.filter(owner=user, deleted_at__isnull=True, date__range=(start, end)).aggregate(t=Sum("amount"))["t"] or D(0)
    out[CROPS]["expenses"] = Expense.objects.filter(owner=user, deleted_at__isnull=True, date__range=(start, end)).aggregate(t=Sum("amount"))["t"] or D(0)
    for r in money(user, start, end):
        out[r["livelihood"]]["income"] += r["income"]
        out[r["livelihood"]]["expenses"] += r["expenses"]
    rows = [{"code": k, "label": LIVELIHOODS[k]["label"], "emoji": LIVELIHOODS[k]["emoji"], **v, "net": v["income"] - v["expenses"]}
            for k, v in out.items() if k in LIVELIHOODS and (v["income"] or v["expenses"])]
    return sorted(rows, key=lambda r: -r["net"])


def send_reminders(today=None) -> int:
    """Once a day: tell each farmer about reminders that fall due today."""
    from notify import service as notify
    from notify.models import InboxItem

    today = today or timezone.localdate()
    sent = 0
    for unit in FarmUnit.objects.filter(active=True).select_related("owner"):
        for t in due_tasks(unit, today):
            related = f"task:{unit.pk}:{t['ref']}"
            if t["date"] != today or InboxItem.objects.filter(user=unit.owner, related=related).exists():
                continue
            notify.tell(unit.owner, "farm_task", related=related, title=unit.name, url=f"/farm/{unit.pk}/", place=unit.name, advice=t["text"],
                        link=f"{settings.SITE_URL}/farm/{unit.pk}/")
            sent += 1
    return sent
