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
