import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class BookRecord(models.Model):
    """Common fields. The app makes `client_id` itself, so records can be created offline and synced later."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    client_id = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        constraints = []

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)


class Plot(BookRecord):
    class Irrigation(models.TextChoices):
        RAINFED = "rainfed", "Rainfed"
        BOREWELL = "borewell", "Borewell"
        CANAL = "canal", "Canal"
        OTHER = "other", "Other"

    name = models.CharField(max_length=80)
    area_acres = models.DecimalField(max_digits=8, decimal_places=2)
    soil = models.CharField(max_length=40, blank=True)
    irrigation = models.CharField(max_length=10, choices=Irrigation.choices, default=Irrigation.RAINFED)
    location_note = models.CharField(max_length=160, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="uniq_plot_client")]


class CropCycle(BookRecord):
    class Season(models.TextChoices):
        KHARIF = "kharif", "Kharif"
        RABI = "rabi", "Rabi"
        ZAID = "zaid", "Zaid"

    class Status(models.TextChoices):
        ACTIVE = "active", "Growing"
        HARVESTED = "harvested", "Harvested"
        CLOSED = "closed", "Closed"

    plot = models.ForeignKey(Plot, on_delete=models.CASCADE, related_name="cycles")
    crop = models.CharField(max_length=60)
    variety = models.CharField(max_length=60, blank=True)
    season = models.CharField(max_length=10, choices=Season.choices, blank=True)
    sowing_date = models.DateField(null=True, blank=True)
    expected_harvest_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="uniq_cycle_client")]


class Activity(BookRecord):
    class Kind(models.TextChoices):
        SOWING = "sowing", "Sowing"
        IRRIGATION = "irrigation", "Irrigation"
        FERTILISER = "fertiliser", "Fertiliser"
        SPRAY = "spray", "Spray"
        WEEDING = "weeding", "Weeding"
        HARVEST = "harvest", "Harvest"
        OTHER = "other", "Other"

    crop_cycle = models.ForeignKey(CropCycle, on_delete=models.CASCADE, related_name="activities")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    date = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    done = models.BooleanField(default=True, help_text="False for a planned task on the harvest calendar")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="uniq_activity_client")]


class Expense(BookRecord):
    class Category(models.TextChoices):
        SEED = "seed", "Seed"
        FERTILISER = "fertiliser", "Fertiliser"
        PESTICIDE = "pesticide", "Pesticide"
        LABOUR = "labour", "Labour"
        IRRIGATION = "irrigation", "Irrigation / diesel"
        MACHINERY = "machinery", "Machinery"
        TRANSPORT = "transport", "Transport"
        OTHER = "other", "Other"

    crop_cycle = models.ForeignKey(CropCycle, null=True, blank=True, on_delete=models.CASCADE, related_name="expenses")
    category = models.CharField(max_length=12, choices=Category.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="uniq_expense_client")]


class Harvest(BookRecord):
    class Grade(models.TextChoices):
        A = "A", "Grade A"
        B = "B", "Grade B"
        C = "C", "Grade C"
        UNGRADED = "ungraded", "Not graded"

    crop_cycle = models.ForeignKey(CropCycle, on_delete=models.CASCADE, related_name="harvests")
    date = models.DateField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=8)
    bag_weight_kg = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=3)
    grade = models.CharField(max_length=10, choices=Grade.choices, default=Grade.UNGRADED)
    storage_note = models.CharField(max_length=160, blank=True)
    shelf_life_days = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="uniq_harvest_client")]


class Sale(BookRecord):
    class Channel(models.TextChoices):
        MANDI = "mandi", "Mandi"
        TRADER = "trader_at_farm", "Trader at farm"
        FPO = "fpo", "FPO"
        DIRECT = "direct_buyer", "Direct buyer"
        OTHER = "other", "Other"

    crop_cycle = models.ForeignKey(CropCycle, on_delete=models.CASCADE, related_name="sales")
    date = models.DateField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=8)
    bag_weight_kg = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=3)
    rate = models.DecimalField(max_digits=12, decimal_places=2, help_text="Rupees per unit sold")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.OTHER)
    buyer_note = models.CharField(max_length=160, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "client_id"], name="uniq_sale_client")]
