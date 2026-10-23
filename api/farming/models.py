"""Group farming: farmers near each other who grow the same crop agree to farm it the same way, then buy and sell together.

A group of 20 farmers with 50 acres of the same wheat variety, sown the same week, is one uniform lot: buyers pay more for
that, input dealers give a bulk rate, and a KVK can guide it as one demonstration. The group's numbers (members, acres,
farmers who keep their book) are shown to buyers, so it is also a mark of trust.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

PRACTICES = [
    ("same_seed", "Same seed variety"),
    ("sow_together", "Sow in the same week"),
    ("buy_inputs", "Buy seed and fertiliser together"),
    ("kvk_advice", "Follow the KVK's advice"),
    ("keep_book", "Every member keeps the Farmer Book"),
    ("grade_together", "Clean and grade together"),
    ("sell_together", "Sell as one lot"),
]


class CropGroup(models.Model):
    class Season(models.TextChoices):
        KHARIF = "kharif", "Kharif (monsoon)"
        RABI = "rabi", "Rabi (winter)"
        ZAID = "zaid", "Zaid (summer)"
        YEAR = "year", "All year"

    class Status(models.TextChoices):
        FORMING = "forming", "Forming: farmers can join"
        ACTIVE = "active", "Farming together"
        CLOSED = "closed", "Closed"

    name = models.CharField(max_length=120)
    crop = models.CharField(max_length=60, db_index=True)
    season = models.CharField(max_length=6, choices=Season.choices)
    year = models.PositiveSmallIntegerField()
    state = models.CharField(max_length=60, db_index=True)
    district = models.CharField(max_length=80, db_index=True)
    village = models.CharField(max_length=120, blank=True, help_text="Village or cluster of villages")
    seed_variety = models.CharField(max_length=80, blank=True)
    practices = models.JSONField(default=list, blank=True)
    note = models.CharField(max_length=300, blank=True)
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="crop_groups")
    centre = models.ForeignKey("extension.Centre", null=True, blank=True, on_delete=models.SET_NULL, related_name="crop_groups", help_text="KVK guiding the group")
    lead = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.FORMING, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class CropGroupMember(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Member"
        LEFT = "left", "Left"

    group = models.ForeignKey(CropGroup, on_delete=models.CASCADE, related_name="members")
    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="crop_groups")
    area_acres = models.DecimalField(max_digits=8, decimal_places=2)
    crop_cycle = models.ForeignKey("farmerbook.CropCycle", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.ACTIVE)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["joined_at"]
        constraints = [models.UniqueConstraint(fields=["group", "farmer"], name="uniq_group_member")]
