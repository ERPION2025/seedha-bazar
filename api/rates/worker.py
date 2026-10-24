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


def news_tick(now=None) -> bool:
    """Read the news and video feeds when they are due (every NEWS_REFRESH_HOURS)."""
    from knowledge import engine  # lazy: the worker serves both rates and news

    if not engine.due(now):
        return False
    out = engine.run_all()
    log.info("news read: %s", out)
    return True


def issues_tick(now=None) -> int:
    """Remind centres about problems waiting a day; once a day, delete voice notes and photos past their keep period."""
    from issues import services as issue_services

    n = issue_services.remind_overdue(now)
    now = now or timezone.now()
    if now.hour == 3 and now.minute < 10:
        issue_services.purge_media()
    return n


def weather_tick(now=None):
    from weather import services as weather_services  # lazy: the worker serves several jobs

    out = weather_services.tick(now)
    if out is not None:
        from engagement import voice
        from storage.services import remind_due  # daily jobs ride on the same once-a-day run
        remind_due()
        from farming.farm import send_reminders
        send_reminders()
        voice.notify_new_matches()
        voice.purge_audio()
    if out:
        log.info("weather alerts: %s", out)
    return out


def advisory_tick(now=None) -> dict:
    """District advisories: the mKisan feed every few hours; IMD warnings once IMD has whitelisted us."""
    from advisory import services as advisory_services

    out = advisory_services.tick(now)
    if out:
        log.info("advisories: %s", out)
    return out


def warehouse_tick(now=None):
    """WDRA's registered-warehouse list: a few states a day, so every state is refreshed about weekly."""
    from storage import wdra

    out = wdra.tick(now)
    if out is not None:
        log.info("WDRA states refreshed: %s", out)
    return out


def loop(poll_seconds: int = 600):
    log.info("worker started; rates every %s hours, news every %s hours", settings.RATES_REFRESH_HOURS, settings.NEWS_REFRESH_HOURS)
    while True:
        for job in (tick, news_tick, issues_tick, weather_tick, advisory_tick, warehouse_tick):
            try:
                job()
            except Exception:
                log.exception("worker job %s failed", job.__name__)
        time.sleep(poll_seconds)
