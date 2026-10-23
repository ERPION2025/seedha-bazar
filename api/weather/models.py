from django.conf import settings
from django.db import models
from django.utils import timezone


class Place(models.Model):
    """Where a village is. Looked up once (OpenStreetMap), else the district's centre from the boundary file."""

    state = models.CharField(max_length=60)
    district = models.CharField(max_length=80)
    village = models.CharField(max_length=120, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    source = models.CharField(max_length=12, help_text="osm (village found) or district (district centre)")
    looked_up_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["state", "district", "village"], name="uniq_place")]


class Forecast(models.Model):
    """A cached 7-day forecast for a point rounded to about 5 km."""

    lat = models.FloatField()
    lon = models.FloatField()
    days = models.JSONField(help_text="[{date, tmax, tmin, rain_mm, rain_prob, wind, gust, humidity, code}]")
    source = models.CharField(max_length=30, default="open-meteo")
    fetched_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["lat", "lon"])]


class Alert(models.Model):
    """Advice for one crop on one farm for one coming day, from the forecast and the crop's stage."""

    class Kind(models.TextChoices):
        RAIN = "rain", "Heavy rain"
        FROST = "frost", "Frost"
        HEAT = "heat", "Heat"
        WIND = "wind", "Strong wind"
        DRY = "dry", "Dry spell"
        DISEASE = "disease", "Disease risk"

    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="weather_alerts")
    crop_cycle = models.ForeignKey("farmerbook.CropCycle", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    crop = models.CharField(max_length=60)
    stage = models.CharField(max_length=12)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    day = models.DateField()
    advice = models.CharField(max_length=300, help_text="English sentence key; shown translated")
    value = models.CharField(max_length=40, blank=True, help_text="The reading behind it, e.g. 42 mm, 3°C")
    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=80, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["day", "kind"]
        constraints = [models.UniqueConstraint(fields=["farmer", "crop", "kind", "day"], name="uniq_weather_alert")]


class Run(models.Model):
    """One row per day the alert run finished, so it runs once a day."""

    day = models.DateField(unique=True)
    result = models.JSONField(default=dict)
    at = models.DateTimeField(default=timezone.now)
