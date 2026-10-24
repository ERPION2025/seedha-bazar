"""District farm advisories: what to do this week, from the people who know.

Three sources feed one list per district:
- KVKs and research agencies write them in Institution Connect, and farmers in that district hear at once;
- the national mKisan advisory feed (KVK scientists across India), read every few hours;
- IMD district weather warnings, once IMD has allowed our server (their API is IP-whitelisted).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Advisory(models.Model):
    class Source(models.TextChoices):
        KVK = "kvk", "KVK or research centre"
        MKISAN = "mkisan", "mKisan (Government of India)"
        IMD = "imd", "IMD weather warning"

    class Kind(models.TextChoices):
        GENERAL = "general", "Crop care"
        WEATHER = "weather", "Weather"
        PEST = "pest", "Pests and diseases"
        LIVESTOCK = "livestock", "Animals"
        FISHERIES = "fish", "Fish"
        HORTICULTURE = "horti", "Fruit and vegetables"

    class Severity(models.TextChoices):
        INFO = "info", "Advice"
        WARNING = "warning", "Be prepared"
        CRITICAL = "critical", "Take action now"

    source = models.CharField(max_length=8, choices=Source.choices, db_index=True)
    external_id = models.CharField(max_length=80, null=True, blank=True, unique=True, help_text="Id at the source, so a feed is read only once")
    centre = models.ForeignKey("extension.Centre", null=True, blank=True, on_delete=models.SET_NULL, related_name="advisories")
    author = models.CharField(max_length=120, blank=True)
    designation = models.CharField(max_length=120, blank=True)
    issuer = models.CharField(max_length=160, blank=True, help_text="e.g. KVK Durg")
    state = models.CharField(max_length=60, blank=True, db_index=True)
    district = models.CharField(max_length=80, blank=True, db_index=True, help_text="Blank: the whole state (or India, if no state)")
    crops = models.JSONField(default=list, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.GENERAL)
    severity = models.CharField(max_length=8, choices=Severity.choices, default=Severity.INFO)
    title = models.CharField(max_length=160, blank=True)
    text = models.TextField(max_length=4000)
    language = models.CharField(max_length=5, default="hi")
    url = models.URLField(blank=True)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    valid_until = models.DateField(null=True, blank=True)
    notified = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-published_at"]
        verbose_name_plural = "advisories"

    def __str__(self):
        return f"{self.get_source_display()}: {self.district or self.state or 'India'}: {self.text[:60]}"


class FeedRun(models.Model):
    """One read of an outside feed (mKisan, IMD), for the console's Data feeds page."""

    feed = models.CharField(max_length=20, db_index=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    fetched = models.PositiveIntegerField(default=0)
    saved = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_at"]
