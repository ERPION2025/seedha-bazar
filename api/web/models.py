from django.db import models
from django.utils import timezone


class Lead(models.Model):
    """Someone who left their details on a landing page or the harvest calculator. Not an account."""

    class Kind(models.TextChoices):
        BUYER = "buyer", "Buyer waitlist"
        FPO = "fpo", "FPO / NGO interest"
        FARMER = "farmer", "Farmer interest"
        CALCULATOR = "calculator", "Harvest calculator"
        CONTACT = "contact", "Contact"

    kind = models.CharField(max_length=12, choices=Kind.choices)
    name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=80, blank=True)
    message = models.CharField(max_length=500, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    attribution = models.JSONField(default=dict, blank=True, help_text="utm_* tags and referrer from the visitor's first page")
    language = models.CharField(max_length=2, blank=True)
    consent = models.BooleanField(default=False)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name or self.phone}"
