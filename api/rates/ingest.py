"""Pull the day's rates from every configured source into the database. Safe to run any number of times."""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .crops import canonical_crop
from .models import MarketRate, RateFetchLog
from .sources.datagov import DataGovInSource

log = logging.getLogger("seedha.rates")
BATCH = 1000
UNIQUE = ["source", "date", "state", "district", "market", "commodity", "variety", "grade"]
UPDATE = ["min_price", "max_price", "modal_price", "crop", "fetched_at"]


def configured_sources():
    key = settings.DATA_GOV_IN_API_KEY
    if not key:
        return []
    return [DataGovInSource(key, settings.RATES_STATES)]


def save_rows(source_name: str, rows) -> tuple[int, int, object]:
    fetched = saved = 0
    latest = None
    batch = []
    now = timezone.now()

    def flush():
        nonlocal saved
        if batch:
            MarketRate.objects.bulk_create(batch, update_conflicts=True, unique_fields=UNIQUE, update_fields=UPDATE)
            saved += len(batch)
            batch.clear()

    for row in rows:
        fetched += 1
        latest = row["date"] if latest is None or row["date"] > latest else latest
        batch.append(MarketRate(source=source_name, crop=canonical_crop(row["commodity"]), fetched_at=now, **row))
        if len(batch) >= BATCH:
            flush()
    flush()
    return fetched, saved, latest


def run_update(sources=None) -> list[RateFetchLog]:
    sources = configured_sources() if sources is None else sources
    if not sources:
        entry = RateFetchLog.objects.create(source="none", status=RateFetchLog.Status.SKIPPED, finished_at=timezone.now(),
                                            message="No rate source is set up. Add DATA_GOV_IN_API_KEY (free from data.gov.in).")
        return [entry]
    logs = []
    for src in sources:
        entry = RateFetchLog.objects.create(source=src.name)
        try:
            with transaction.atomic():
                fetched, saved, latest = save_rows(src.name, src.fetch())
            entry.rows_fetched, entry.rows_saved, entry.latest_date = fetched, saved, latest
            entry.status = RateFetchLog.Status.OK if saved else RateFetchLog.Status.FAILED
            entry.message = "" if saved else "The source answered but sent no usable rows."
        except Exception as e:  # one broken source must not stop the others
            log.exception("rate source %s failed", src.name)
            entry.status, entry.message = RateFetchLog.Status.FAILED, f"{type(e).__name__}: {e}"[:300]
        entry.finished_at = timezone.now()
        entry.save()
        logs.append(entry)
    return logs
