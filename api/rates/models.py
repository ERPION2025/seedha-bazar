from django.db import models
from django.utils import timezone


class MarketRate(models.Model):
    """One day's reported price for one commodity in one mandi. Prices are rupees per quintal."""

    source = models.CharField(max_length=20, default="agmarknet", help_text="agmarknet = Govt. of India via data.gov.in; demo = sample data")
    date = models.DateField(db_index=True)
    state = models.CharField(max_length=60)
    district = models.CharField(max_length=80)
    market = models.CharField(max_length=120)
    commodity = models.CharField(max_length=120)
    variety = models.CharField(max_length=120, blank=True)
    grade = models.CharField(max_length=40, blank=True)
    crop = models.CharField(max_length=20, blank=True, db_index=True, help_text="Our crop key, empty if we do not track it")
    min_price = models.DecimalField(max_digits=10, decimal_places=2)
    max_price = models.DecimalField(max_digits=10, decimal_places=2)
    modal_price = models.DecimalField(max_digits=10, decimal_places=2)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "date", "state", "district", "market", "commodity", "variety", "grade"], name="uniq_market_rate")]
        indexes = [models.Index(fields=["crop", "state", "-date"]), models.Index(fields=["state", "district", "-date"])]
        ordering = ["-date", "state", "district", "market"]

    def __str__(self):
        return f"{self.commodity} @ {self.market} {self.date}: {self.modal_price}"


class RateFetchLog(models.Model):
    class Status(models.TextChoices):
        OK = "ok", "OK"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    source = models.CharField(max_length=20)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.FAILED)
    rows_fetched = models.PositiveIntegerField(default=0)
    rows_saved = models.PositiveIntegerField(default=0)
    latest_date = models.DateField(null=True, blank=True)
    message = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_at"]


class MspPrice(models.Model):
    """Government minimum support price, announced once a season. Entered from the official notification."""

    crop = models.CharField(max_length=20)
    name = models.CharField(max_length=80, help_text="As written in the notification, e.g. Paddy (Common)")
    season = models.CharField(max_length=20, help_text="e.g. RMS 2027-28 or KMS 2026-27")
    price_per_quintal = models.DecimalField(max_digits=10, decimal_places=2)
    announced_on = models.DateField(null=True, blank=True)
    source_url = models.URLField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["crop", "name", "season"], name="uniq_msp")]
        ordering = ["crop", "-season"]


class GeoCache(models.Model):
    """Which district a ~1 km map square is in, so the map service is asked once. Not linked to any person."""

    lat = models.DecimalField(max_digits=6, decimal_places=2)
    lon = models.DecimalField(max_digits=6, decimal_places=2)
    state = models.CharField(max_length=80)
    district = models.CharField(max_length=80)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lat", "lon"], name="uniq_geo_square")]


class RateAlert(models.Model):
    """A signed-in person who wants today's rate for a crop sent to their own phone."""

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"

    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="rate_alerts")
    crop = models.CharField(max_length=20)
    state = models.CharField(max_length=60, blank=True)
    district = models.CharField(max_length=80, blank=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.WHATSAPP)
    language = models.CharField(max_length=2, default="hi")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sent_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "crop", "channel"], name="uniq_rate_alert")]
