from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.Model):
    """An insurance option for a crop in a state and season.

    Rows with a blank state are the national rules (farmer's premium share by crop group) and apply everywhere until
    a state's own notification is loaded. A state row adds what the state notified: which crops and districts, the sum
    insured per hectare, the cut-off date and the insurance company. `notified` says whether this row comes from that notification.
    """

    class Scheme(models.TextChoices):
        PMFBY = "pmfby", "PM Fasal Bima Yojana"
        RWBCIS = "rwbcis", "Weather-based crop insurance (RWBCIS)"
        STATE = "state", "State scheme"

    class Season(models.TextChoices):
        KHARIF = "kharif", "Kharif"
        RABI = "rabi", "Rabi"
        ANNUAL = "annual", "Annual (commercial and horticulture)"

    class Group(models.TextChoices):
        FOOD = "food", "Food grains and oilseeds"
        COMMERCIAL = "commercial", "Commercial and horticulture crops"

    scheme = models.CharField(max_length=8, choices=Scheme.choices, default=Scheme.PMFBY)
    state = models.CharField(max_length=60, blank=True, db_index=True)
    season = models.CharField(max_length=8, choices=Season.choices)
    group = models.CharField(max_length=12, choices=Group.choices, blank=True, help_text="For national rules: the crop group")
    crop = models.CharField(max_length=60, blank=True, db_index=True, help_text="Catalog key, for a state's notified crop")
    districts = models.JSONField(default=list, blank=True, help_text="Blank for the whole state")
    farmer_share_pct = models.DecimalField(max_digits=5, decimal_places=2, help_text="Premium the farmer pays, as % of the sum insured")
    sum_insured_per_ha = models.DecimalField(max_digits=10, decimal_places=0, null=True, blank=True)
    cutoff_date = models.DateField(null=True, blank=True, help_text="Last day to enrol")
    insurer = models.CharField(max_length=160, blank=True)
    risks = models.CharField(max_length=300, blank=True)
    notified = models.BooleanField(default=False)
    source = models.CharField(max_length=300, blank=True)
    last_checked = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["state", "crop", "season", "scheme"]

    def __str__(self):
        return f"{self.get_scheme_display()} · {self.state or 'All India'} · {self.crop or self.group} · {self.season}"


class Application(models.Model):
    """A farmer opting in. Until a partner connection exists, Seedha Bazar prepares and tracks; the farmer (or their FPO) submits at a bank, CSC or the portal."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Being prepared"
        READY = "ready", "Ready to submit"
        SUBMITTED = "submitted", "Submitted"
        ENROLLED = "enrolled", "Insured"
        LOSS = "loss", "Loss reported"
        CLAIM_PAID = "claim_paid", "Claim paid"
        CLOSED = "closed", "Closed"

    class Channel(models.TextChoices):
        BANK = "bank", "My bank"
        CSC = "csc", "Common Service Centre"
        PORTAL = "portal", "pmfby.gov.in myself"
        FPO = "fpo", "Through my FPO"

    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="insurance_applications")
    helped_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", help_text="FPO agent who prepared it")
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="insurance_applications")
    crop_cycle = models.ForeignKey("farmerbook.CropCycle", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    plan = models.ForeignKey(Plan, null=True, on_delete=models.SET_NULL, related_name="applications")
    crop = models.CharField(max_length=60)
    season = models.CharField(max_length=8, choices=Plan.Season.choices)
    year = models.PositiveSmallIntegerField()
    state = models.CharField(max_length=60)
    district = models.CharField(max_length=80)
    village = models.CharField(max_length=120, blank=True)
    area_ha = models.DecimalField(max_digits=8, decimal_places=3)
    sum_insured = models.DecimalField(max_digits=12, decimal_places=0)
    farmer_premium = models.DecimalField(max_digits=10, decimal_places=0)
    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.BANK)
    loanee = models.BooleanField(default=False, help_text="Has a crop loan / KCC (the bank enrols unless the farmer opts out)")
    checklist = models.JSONField(default=dict, blank=True, help_text="Which papers are ready")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    application_no = models.CharField(max_length=60, blank=True)
    policy_no = models.CharField(max_length=60, blank=True)
    insurer = models.CharField(max_length=160, blank=True)
    loss_date = models.DateField(null=True, blank=True)
    loss_cause = models.CharField(max_length=40, blank=True)
    loss_note = models.CharField(max_length=500, blank=True)
    claim_amount = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    connector = models.CharField(max_length=30, default="manual", help_text="Which connector handles it")
    connector_ref = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def govt_share(self) -> Decimal:
        """What the government pays towards the premium is not known to us; this is the part of the cover the farmer did not pay for."""
        return self.sum_insured - self.farmer_premium
