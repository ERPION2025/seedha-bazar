"""Connectors. A backend has one method, `send(message)`, and returns a provider message id (or None).

To connect a provider (MSG91, Twilio, Gupshup, WhatsApp Cloud API...): subclass Backend, call their API in `send`, raise on failure,
and point NOTIFY_BACKENDS at your class, e.g. {"sms": "myapp.msg91.Msg91Sms", "whatsapp": "myapp.wa.CloudApi"}.
Or use WebhookBackend and let an automation tool (n8n, Make, Zapier) or your own service do the sending.
"""
import hashlib
import hmac
import json
import logging
import urllib.request

from django.conf import settings

from config.netutil import ssl_context

log = logging.getLogger("seedha.notify")


class Backend:
    name = "base"
    delivers = True  # False for backends that only record the message

    def send(self, message) -> str | None:
        raise NotImplementedError


class LogBackend(Backend):
    """Default until a provider is connected: writes the message to the log and the outbox, delivers nothing."""

    name = "log"
    delivers = False

    def send(self, message):
        log.warning("[%s to %s] %s", message.channel, message.phone, message.text)
        return None


class WebhookBackend(Backend):
    """POSTs a small JSON document to NOTIFY_WEBHOOK_URL. If NOTIFY_WEBHOOK_SECRET is set, the body is signed:
    header X-Seedha-Signature = hex HMAC-SHA256(secret, body)."""

    name = "webhook"

    def send(self, message):
        body = json.dumps({"id": message.pk, "channel": message.channel, "to": message.phone, "template": message.template,
                           "language": message.language, "text": message.text, "params": message.params}).encode()
        headers = {"Content-Type": "application/json", "User-Agent": "SeedhaBazar/1.0"}
        if settings.NOTIFY_WEBHOOK_SECRET:
            headers["X-Seedha-Signature"] = hmac.new(settings.NOTIFY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(settings.NOTIFY_WEBHOOK_URL, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as resp:
            resp.read()
            return str(resp.headers.get("X-Message-Id", ""))


class MemoryBackend(Backend):
    """For tests."""

    name = "memory"
    outbox: list = []

    def send(self, message):
        self.outbox.append(message)
        return f"mem-{message.pk}"


class WhatsAppCloudBackend(Backend):
    """WhatsApp Business Cloud API (Meta). Sends the approved utility template WHATSAPP_TEMPLATE with our text as its one variable.

    Business-initiated WhatsApp messages must use a template approved by Meta; free text works only within 24 hours of the
    person's last message. Set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID; see Console > Settings.
    """

    name = "whatsapp-cloud"
    LANG = {"hi": "hi", "mr": "mr", "en": "en"}

    def send(self, message):
        digits = "".join(c for c in message.phone if c.isdigit())
        to = digits if len(digits) > 10 else "91" + digits
        body = {"messaging_product": "whatsapp", "to": to, "type": "template",
                "template": {"name": settings.WHATSAPP_TEMPLATE, "language": {"code": self.LANG.get(message.language, "hi")},
                             "components": [{"type": "body", "parameters": [{"type": "text", "text": message.text[:1000]}]}]}}
        url = f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as resp:
            data = json.loads(resp.read())
        return (data.get("messages") or [{}])[0].get("id", "")


class MessengerBackend(Backend):
    """Facebook Messenger from the Seedha Bazar Page. `message.phone` carries the person's Page-scoped id (PSID).

    Meta lets a Page message someone freely only within 24 hours of their last message to it; callers check that first.
    """

    name = "messenger"

    def send(self, message):
        body = {"recipient": {"id": message.phone}, "messaging_type": "RESPONSE", "message": {"text": message.text[:1900]}}
        url = f"https://graph.facebook.com/{settings.FACEBOOK_GRAPH_VERSION}/me/messages?access_token={settings.FACEBOOK_PAGE_TOKEN}"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15, context=ssl_context()) as resp:
            data = json.loads(resp.read())
        return data.get("message_id", "")
