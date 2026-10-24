from django.conf import settings
from django.db import models
from django.utils import timezone


class Notice(models.Model):
    """A message a KVK or agency sends to farmers, FPOs and NGOs of its districts."""

    class Audience(models.TextChoices):
        ALL = "all", "Farmers, FPOs and NGOs"
        FARMERS = "farmers", "Farmers only"
        ORGS = "orgs", "FPOs and NGOs only"

    centre = models.ForeignKey("extension.Centre", on_delete=models.CASCADE, related_name="notices")
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.ALL)
    districts = models.JSONField(default=list)
    crop = models.CharField(max_length=60, blank=True)
    text = models.CharField(max_length=300)
    sent = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
