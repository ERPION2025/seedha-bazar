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


def send(channel: str, phone: str, template: str, lang: str = "hi", user=None, related: str = "", **params) -> Message:
    """Queue and deliver one message. Never raises: the outcome is on the returned Message (status, error)."""
    text = texts.render(template, lang, params)
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


def tell(user, template: str, related: str = "", title: str = "Seedha Bazar", url: str = "/", critical: bool = False, **params) -> dict:
    """Reach a person on every channel they have allowed: phone notification, Messenger (inside Meta's 24-hour window),
    WhatsApp (if they agreed), and SMS. Returns what was tried. Never raises."""
    from datetime import timedelta

    from . import push
    from .models import Preference

    pref = Preference.objects.filter(user=user).first()
    lang = getattr(user, "language", "hi")
    text = texts.render(template, lang, params)
    out = {"push": 0, "messenger": None, "whatsapp": None, "sms": None}
    if pref is None or pref.push:
        out["push"] = push.send(user, title, text, url, tag=related, critical=critical)
    if pref and pref.messenger_psid and pref.messenger_last_in and timezone.now() - pref.messenger_last_in < timedelta(hours=23):
        out["messenger"] = send("messenger", pref.messenger_psid, template, lang, user=user, related=related, **params).status
    if pref and pref.whatsapp:
        out["whatsapp"] = send("whatsapp", user.phone, template, lang, user=user, related=related, **params).status
    if pref is None or pref.sms or not any(out.values()):
        out["sms"] = send("sms", user.phone, template, lang, user=user, related=related, **params).status
    return out
