from django.db import models
from django.utils import timezone


class Message(models.Model):
    """Every SMS or WhatsApp message the platform wants to send. Providers are plugged in behind `notify.service.send`."""

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent to provider"
        LOGGED = "logged", "Logged only (no provider connected)"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked (opt-out or daily limit)"

    channel = models.CharField(max_length=10, choices=Channel.choices)
    phone = models.CharField(max_length=20, db_index=True)
    template = models.CharField(max_length=40)
    language = models.CharField(max_length=2, default="hi")
    params = models.JSONField(default=dict, blank=True)
    text = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    provider = models.CharField(max_length=40, blank=True)
    provider_id = models.CharField(max_length=120, blank=True)
    error = models.CharField(max_length=300, blank=True)
    user = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    related = models.CharField(max_length=60, blank=True, help_text="What triggered it, e.g. calculator, rate_alert, enquiry:12")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class OptOut(models.Model):
    """Numbers that asked us to stop. Nothing is sent to them."""

    phone = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=120, blank=True)
