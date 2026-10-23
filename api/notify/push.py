"""Phone and browser notifications (Web Push with VAPID keys). Free; works while the browser is closed on Android.

The notification itself uses the phone's own notification sound. Seedha Bazar's tune plays inside the app (alarm.js);
a custom tune in the notification shade needs the site wrapped as an Android app (Trusted Web Activity).
"""
import json
import logging

from django.conf import settings
from django.utils import timezone

from .models import PushSubscription

log = logging.getLogger("seedha.notify")


def configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send(user, title: str, body: str, url: str = "/", tag: str = "", critical: bool = False) -> int:
    """Send to every device the person has allowed. Returns how many accepted it. Dead subscriptions are removed."""
    if not configured():
        return 0
    from pywebpush import WebPushException, webpush

    payload = json.dumps({"title": title, "body": body[:240], "url": url, "tag": tag or "seedha", "critical": critical})
    ok = 0
    for sub in PushSubscription.objects.filter(user=user):
        try:
            webpush(subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}, data=payload,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY, vapid_claims={"sub": settings.VAPID_EMAIL}, ttl=12 * 3600,
                    headers={"Urgency": "high" if critical else "normal"})
            sub.last_ok, sub.failures = timezone.now(), 0
            sub.save(update_fields=["last_ok", "failures"])
            ok += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                sub.delete()  # the browser forgot it
            else:
                sub.failures += 1
                sub.save(update_fields=["failures"])
                log.warning("push failed for %s: %s", user.pk, e)
        except Exception as e:  # noqa: BLE001 - never let a notification break the caller
            log.warning("push failed for %s: %s", user.pk, e)
    return ok
