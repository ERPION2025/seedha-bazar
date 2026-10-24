"""Krishi Vigyan Kendras and research centres: who they are, which districts they look after, and what they do on the platform.

A centre's districts are its geofence: its staff see farmers, FPOs, NGOs, stock, sales and issues only for those districts.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Centre(models.Model):
    class Kind(models.TextChoices):
        KVK = "kvk", "Krishi Vigyan Kendra (KVK)"
        RESEARCH = "research", "Research centre / ICAR institute"
        UNIVERSITY = "university", "Agricultural university"
        DEPARTMENT = "department", "Agriculture department office"

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.KVK)
    state = models.CharField(max_length=60, db_index=True)
    districts = models.JSONField(default=list, help_text="Districts this centre looks after (its geofence)")
    host = models.CharField(max_length=200, blank=True, help_text="Host institution, e.g. the agricultural university")
    address = models.CharField(max_length=300, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    verified = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["state", "name"]

    def __str__(self):
        return self.name

    def covers(self, state: str, district: str) -> bool:
        from .geo import same_district

        return (not state or state.lower() == self.state.lower()) and any(same_district(d, district) for d in self.districts)


class CentreMember(models.Model):
    class Role(models.TextChoices):
        HEAD = "head", "Head / Senior scientist"
        EXPERT = "expert", "Subject matter specialist"
        STAFF = "staff", "Staff"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="centre_memberships")
    centre = models.ForeignKey(Centre, on_delete=models.CASCADE, related_name="members")
    name = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.EXPERT)
    speciality = models.CharField(max_length=80, blank=True, help_text="e.g. Plant protection, Soil science, Horticulture")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "centre"], name="uniq_centre_member")]


class InputOffer(models.Model):
    """Seed, fertiliser, bio-inputs, saplings or services a centre offers to farmers and FPOs in its districts."""

    class Kind(models.TextChoices):
        SEED = "seed", "Seed"
        FERTILISER = "fertiliser", "Fertiliser"
        BIO = "bio", "Bio-fertiliser or bio-pesticide"
        SAPLING = "sapling", "Saplings and planting material"
        PROTECTION = "protection", "Plant protection"
        EQUIPMENT = "equipment", "Machine or tool on hire"
        TRAINING = "training", "Training or demonstration"
        TESTING = "testing", "Soil or water testing"

    class Audience(models.TextChoices):
        ALL = "all", "Farmers and FPOs"
        FARMERS = "farmers", "Farmers"
        FPOS = "fpos", "FPOs and NGOs"

    centre = models.ForeignKey(Centre, on_delete=models.CASCADE, related_name="offers")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    name = models.CharField(max_length=160, help_text="e.g. Wheat seed, variety HI-1544")
    crop = models.CharField(max_length=60, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, help_text="How much is available in total")
    unit = models.CharField(max_length=20, default="kg")
    per_person_limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Rupees per unit. 0 = free")
    note = models.CharField(max_length=400, blank=True, help_text="Who qualifies, how to use, what to bring")
    pickup = models.CharField(max_length=200, blank=True)
    districts = models.JSONField(default=list, help_text="Blank = all the centre's districts")
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.ALL)
    valid_until = models.DateField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    @property
    def taken(self):
        from decimal import Decimal
        return sum((r.quantity for r in self.requests.exclude(status__in=["declined", "cancelled"])), Decimal(0))

    @property
    def left(self):
        return max(self.quantity - self.taken, 0)

    @property
    def is_live(self) -> bool:
        return self.active and self.valid_until >= timezone.localdate() and self.left > 0


class InputRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved, collect it"
        COLLECTED = "collected", "Collected"
        DECLINED = "declined", "Not approved"
        CANCELLED = "cancelled", "Cancelled"

    offer = models.ForeignKey(InputOffer, on_delete=models.CASCADE, related_name="requests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="input_requests")
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED)
    centre_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
