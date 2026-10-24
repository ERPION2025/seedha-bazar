"""The daily refresh. `due()` is the whole schedule: refresh when the last good fetch is a day old, and retry a failure after an hour."""
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import ingest
from .models import RateFetchLog

log = logging.getLogger("seedha.rates")


def due(now=None) -> bool:
    now = now or timezone.now()
    if not settings.DATA_GOV_IN_API_KEY:
        return False
    last = RateFetchLog.objects.exclude(status=RateFetchLog.Status.SKIPPED).first()
    if last is None:
        return True
    last_ok = RateFetchLog.objects.filter(status=RateFetchLog.Status.OK).first()
    if last_ok and now - last_ok.started_at < timedelta(hours=settings.RATES_REFRESH_HOURS) - timedelta(minutes=10):
        return False
    return last.status == RateFetchLog.Status.OK or now - last.started_at >= timedelta(hours=1)


def tick(now=None) -> bool:
    """One pass of the worker loop. Returns True if it fetched."""
    if not due(now):
        return False
    logs = ingest.run_update()
    if any(entry.status == RateFetchLog.Status.OK for entry in logs):
        from web import rate_alerts  # lazy: web depends on rates

        try:
            n = rate_alerts.send_daily_alerts()
            log.info("rate alerts sent: %s", n)
        except Exception:
            log.exception("rate alerts failed")
    return True


def loop(poll_seconds: int = 600):
    log.info("rates worker started; refresh every %s hours", settings.RATES_REFRESH_HOURS)
    while True:
        try:
            tick()
        except Exception:
            log.exception("rates worker pass failed")
        time.sleep(poll_seconds)
