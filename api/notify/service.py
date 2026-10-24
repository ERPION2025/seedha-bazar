from datetime import timedelta
from importlib import import_module
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from . import texts
from .models import Message, OptOut


def backend_for(channel: str):
    path = settings.NOTIFY_BACKENDS.get(channel, "notify.backends.LogBackend")
    module, _, cls = path.rpartition(".")
    return getattr(import_module(module), cls)()


KIND_OF = {"kvk_notice": "notice", "system_notice": "system", "advisory": "advisory", "weather_alert": "weather", "group_invite": "group",
           "input_offer": "input", "input_update": "input", "issue_alert": "issue", "issue_reply": "issue", "deal_request": "order", "deal_update": "order",
           "pool_invite": "market", "farm_task": "farm", "pool_paid": "market", "pledge_due": "other", "interest_news": "other"}
TITLE_OF = {"notice": "Message from your KVK", "system": "Seedha Bazar", "advisory": "New advice for your district", "weather": "Weather warning",
            "order": "Update on your order", "market": "Group selling", "group": "Group farming", "input": "Seeds and inputs", "issue": "Your problem",
            "farm": "Farm reminder", "other": "Seedha Bazar"}


def _path(link: str) -> str:
    """Links in messages are full addresses; the bell keeps the path, so it opens on whichever site the person uses."""
    for base in (settings.SITE_URL, settings.INSTITUTION_URL):
        if link.startswith(base):
            return link[len(base):] or "/"
    return link if link.startswith("/") else ""


def to_inbox(user, template: str, text: str, url: str = "", title: str = "", related: str = "", critical: bool = False):
    """Keep a copy for the bell in the header. A repeat of the same message within two minutes is not kept twice."""
    from .models import InboxItem

    if user is None or not getattr(user, "pk", None):
        return None
    recent = timezone.now() - timedelta(minutes=2)
    if related and InboxItem.objects.filter(user=user, template=template, related=related, created_at__gte=recent).exists():
        return None
    kind = KIND_OF.get(template, "other")
    if not title or title == "Seedha Bazar":
        from web.i18n import tr
        title = tr(getattr(user, "language", "hi"), TITLE_OF[kind])
    return InboxItem.objects.create(user=user, kind=kind, title=title[:160], text=text[:600], url=_path(url)[:300], critical=critical, template=template,
                                    related=related[:60])


def send(channel: str, phone: str, template: str, lang: str = "hi", user=None, related: str = "", inbox: bool = True, **params) -> Message:
    """Queue and deliver one message. Never raises: the outcome is on the returned Message (status, error).
    A message to a known person is also kept for the bell in the app (unless `inbox=False`)."""
    text = texts.render(template, lang, params)
    if inbox and user is not None and channel != "messenger":
        to_inbox(user, template, text, params.get("link", ""), related=related)
    msg = Message(channel=channel, phone=phone, template=template, language=lang, params=params, text=text, user=user, related=related)
    blocked = None
    if OptOut.objects.filter(phone=phone).exists():
        blocked = "opted_out"
    elif Message.objects.filter(phone=phone, created_at__gte=timezone.now() - timedelta(days=1)).exclude(status=Message.Status.BLOCKED).count() >= settings.NOTIFY_MAX_PER_PHONE_PER_DAY:
        blocked = "daily_limit"
    if blocked:
        msg.status, msg.error = Message.Status.BLOCKED, blocked
        msg.save()
        return msg
    msg.save()
    backend = backend_for(channel)
    msg.provider = backend.name
    try:
        msg.provider_id = backend.send(msg) or ""
        msg.status = Message.Status.SENT if backend.delivers else Message.Status.LOGGED
        msg.sent_at = timezone.now()
    except Exception as e:
        msg.status, msg.error = Message.Status.FAILED, f"{type(e).__name__}: {e}"[:300]
    msg.save()
    return msg


def wa_link(text: str, phone: str = "") -> str:
    """A WhatsApp click-to-chat link. Works with no provider: the person's own WhatsApp opens with the text ready."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}?text={quote(text)}"


def sms_link(text: str, phone: str = "") -> str:
    return f"sms:{phone}?body={quote(text)}"


def tell(user, template: str, related: str = "", title: str = "Seedha Bazar", url: str = "/", critical: bool = False, quiet: bool = False, **params) -> dict:
    """Reach a person on every channel they have allowed: the bell in the app (always), phone notification, Messenger
    (inside Meta's 24-hour window), WhatsApp (if they agreed), and SMS. `quiet` keeps it to the bell and phone notifications
    (no paid SMS or WhatsApp), for broadcasts. Returns what was tried. Never raises."""
    from datetime import timedelta

    from . import push
    from .models import Preference

    pref = Preference.objects.filter(user=user).first()
    lang = getattr(user, "language", "hi")
    text = texts.render(template, lang, params)
    to_inbox(user, template, text, url, title, related, critical)
    out = {"push": 0, "messenger": None, "whatsapp": None, "sms": None}
    if quiet:
        out["push"] = push.send(user, title, text, url, tag=related, critical=critical)
        return out
    if pref is None or pref.push:
        out["push"] = push.send(user, title, text, url, tag=related, critical=critical)
    if pref and pref.messenger_psid and pref.messenger_last_in and timezone.now() - pref.messenger_last_in < timedelta(hours=23):
        out["messenger"] = send("messenger", pref.messenger_psid, template, lang, user=user, related=related, inbox=False, **params).status
    if pref and pref.whatsapp:
        out["whatsapp"] = send("whatsapp", user.phone, template, lang, user=user, related=related, inbox=False, **params).status
    if pref is None or pref.sms or not any(out.values()):
        out["sms"] = send("sms", user.phone, template, lang, user=user, related=related, inbox=False, **params).status
    return out
