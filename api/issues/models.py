"""Problems farmers and FPOs raise (pests, disease, soil, seed, weather damage...), routed to the KVK or research centre
whose districts cover them. Raised by typing, speaking (turned into text on the phone) or a short voice note."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def private_path(instance, filename):
    ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()[:5]
    return f"private/issues/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class Issue(models.Model):
    class Category(models.TextChoices):
        PEST = "pest", "Pests or insects"
        DISEASE = "disease", "Plant disease"
        SOIL = "soil", "Soil and fertiliser"
        SEED = "seed", "Seed quality"
        WATER = "water", "Water and irrigation"
        WEATHER = "weather", "Weather damage"
        CROP_LOSS = "crop_loss", "Crop loss (insurance)"
        LIVESTOCK = "livestock", "Animals and livestock"
        MARKET = "market", "Selling and prices"
        SCHEME = "scheme", "Schemes and paperwork"
        MACHINE = "machine", "Machines and tools"
        OTHER = "other", "Something else"

    class Status(models.TextChoices):
        OPEN = "open", "Waiting for an expert"
        ACKNOWLEDGED = "acknowledged", "An expert is looking"
        ADVISED = "advised", "Advice given"
        RESOLVED = "resolved", "Solved"
        CLOSED = "closed", "Closed"

    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="issues_raised")
    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues", help_text="The farmer it is about (an FPO may raise it for a member)")
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues")
    centre = models.ForeignKey("extension.Centre", null=True, blank=True, on_delete=models.SET_NULL, related_name="issues")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="issues_assigned")
    state = models.CharField(max_length=60, db_index=True)
    district = models.CharField(max_length=80, db_index=True)
    village = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.OTHER)
    crop = models.CharField(max_length=60, blank=True)
    description = models.TextField(max_length=2000)
    via_voice = models.BooleanField(default=False, help_text="The text was spoken and turned into text on the phone")
    voice_note = models.FileField(upload_to=private_path, blank=True)
    photo = models.FileField(upload_to=private_path, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    urgent = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN, db_index=True)
    source = models.CharField(max_length=20, default="app", help_text="app, insurance_loss, order")
    related = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(default=timezone.now)
    first_response_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    farmer_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def title(self) -> str:
        words = self.description.split()
        return " ".join(words[:12]) + ("…" if len(words) > 12 else "")


class Reply(models.Model):
    class Kind(models.TextChoices):
        REPLY = "reply", "Reply"
        ADVICE = "advice", "Advice"
        VISIT = "visit", "Field visit planned"
        NOTE = "note", "Note for the centre only"

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="replies")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.REPLY)
    text = models.TextField(max_length=2000)
    via_voice = models.BooleanField(default=False)
    voice_note = models.FileField(upload_to=private_path, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
