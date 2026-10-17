"""OTP delivery. Swap the backend with settings.OTP_BACKEND (dotted path).

Production note: SMS needs a DLT-registered sender and approved templates, and
WhatsApp needs an approved authentication template. Implement one class per
provider with the same `send` signature and point OTP_BACKEND at it.
"""
import logging
from importlib import import_module

from django.conf import settings

log = logging.getLogger("seedha.messaging")

MESSAGES = {
    "hi": "सीधा बाज़ार: आपका OTP {code} है। इसे किसी को न बताएँ।",
    "mr": "सीधा बाज़ार: तुमचा OTP {code} आहे. हा कोणालाही सांगू नका.",
    "en": "Seedha Bazar: your OTP is {code}. Do not share it with anyone.",
}


class BaseBackend:
    def send(self, phone: str, text: str, channel: str, code: str | None = None) -> None:
        raise NotImplementedError


class ConsoleBackend(BaseBackend):
    """Development only: prints the message. Never use in production."""

    def send(self, phone, text, channel, code=None):
        log.warning("[OTP %s to %s] %s", channel, phone, text)
        print(f"[OTP {channel} to {phone}] {text}")


class MemoryBackend(BaseBackend):
    """Tests: keeps messages in a list."""

    outbox: list[dict] = []

    def send(self, phone, text, channel, code=None):
        self.outbox.append({"phone": phone, "text": text, "channel": channel, "code": code})


def get_backend() -> BaseBackend:
    path = settings.OTP_BACKEND
    if path == "console":
        return ConsoleBackend()
    module, _, cls = path.rpartition(".")
    return getattr(import_module(module), cls)()


def send_otp(phone: str, code: str, channel: str, language: str = "hi") -> None:
    text = MESSAGES.get(language, MESSAGES["hi"]).format(code=code)
    if channel == "voice":
        # Voice reads the code digit by digit, slowly.
        spoken = " ".join(code)
        text = MESSAGES.get(language, MESSAGES["hi"]).format(code=spoken)
    get_backend().send(phone, text, channel, code)


def send_notice(phone: str, text: str) -> None:
    get_backend().send(phone, text, "sms", None)
