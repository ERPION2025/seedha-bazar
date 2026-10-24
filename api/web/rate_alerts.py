"""Daily rate messages to people who asked for them. Runs after each successful rate fetch."""
from django.utils import timezone

from notify import service as notify
from rates import services
from rates.crops import CROPS
from rates.fmt import inr
from rates.models import RateAlert

from .i18n import tr

MAX_AGE_DAYS = 3  # never send a price older than this as if it were today's


def build_params(q: dict, lang: str) -> dict:
    place = q["district"] if q["scope"] == "district" else q["state"] or "India"
    msp = tr(lang, " Govt MSP: {price}.", price=inr(q["msp"]["price"])) if q["msp"] else ""
    return {"crop": tr(lang, CROPS[q["crop"]]), "place": place, "date": q["as_of"].strftime("%d %b"), "price": inr(q["typical"]), "msp": msp}


def send_daily_alerts(today=None) -> int:
    today = today or timezone.localdate()
    sent = 0
    for alert in RateAlert.objects.filter(active=True).select_related("user"):
        if alert.last_sent_on == today or not alert.user.is_active:
            continue
        q = services.quote(alert.crop, alert.state, alert.district)
        if q["typical"] is None or q["as_of"] is None or (today - q["as_of"]).days > MAX_AGE_DAYS:
            continue
        msg = notify.send(alert.channel, alert.user.phone, "rate_alert", alert.language, user=alert.user, related="rate_alert", **build_params(q, alert.language))
        if msg.status in ("sent", "logged"):
            alert.last_sent_on = today
            alert.save(update_fields=["last_sent_on"])
            sent += 1
    return sent
