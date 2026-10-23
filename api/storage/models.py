"""Store produce in a WDRA-registered warehouse, get an electronic Negotiable Warehouse Receipt (e-NWR), and borrow
against it from a bank (e-Kisan Upaj Nidhi). Seedha Bazar does not issue receipts or lend: it helps plan, keeps the
record in the Farmer Book, and reminds before the loan falls due."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Warehouse(models.Model):
    class Repository(models.TextChoices):
        NERL = "nerl", "NERL (National E-Repository Ltd)"
        CCRL = "ccrl", "CCRL (CDSL Commodity Repository Ltd)"
        NONE = "", "Not known"

    name = models.CharField(max_length=200)
    operator = models.CharField(max_length=200, blank=True)
    wdra_reg_no = models.CharField(max_length=60, blank=True, help_text="WDRA registration number")
    repository = models.CharField(max_length=4, choices=Repository.choices, blank=True)
    state = models.CharField(max_length=60, db_index=True)
    district = models.CharField(max_length=80, db_index=True)
    address = models.CharField(max_length=300, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    capacity_mt = models.DecimalField(max_digits=10, decimal_places=1, null=True, blank=True)
    commodities = models.CharField(max_length=300, blank=True)
    storage_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, help_text="Rupees per quintal per month, if known")
    phone = models.CharField(max_length=40, blank=True)
    verified = models.BooleanField(default=False, help_text="Checked against the WDRA list")
    wdra_status = models.CharField(max_length=30, blank=True, db_index=True, help_text="As WDRA lists it: Active, Inactive, Cancelled... 'Not listed' once it drops off")
    remarks = models.CharField(max_length=200, blank=True, help_text="WDRA's remark, e.g. insufficient insurance")
    registered_on = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=8, default="manual", help_text="wdra: read from the WDRA public list; manual: added by hand or CSV")
    last_seen_at = models.DateTimeField(null=True, blank=True, help_text="Last time the WDRA list showed it")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["state", "district", "name"]

    def __str__(self):
        return self.name


class WarehouseSync(models.Model):
    """One read of one state's page of the WDRA public list of registered warehouses."""

    state = models.CharField(max_length=60, db_index=True)
    state_code = models.CharField(max_length=4)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    rows = models.PositiveIntegerField(default=0)
    added = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    gone = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-started_at"]


class Pledge(models.Model):
    """One lot stored in a warehouse, with its e-NWR and the loan against it."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        STORED = "stored", "In the warehouse, e-NWR issued"
        LOAN = "loan", "Loan taken"
        CLOSED = "closed", "Loan repaid or stock sold"

    farmer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pledges")
    crop_cycle = models.ForeignKey("farmerbook.CropCycle", on_delete=models.CASCADE, related_name="+")
    product = models.CharField(max_length=60)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=3)
    warehouse = models.ForeignKey(Warehouse, null=True, blank=True, on_delete=models.SET_NULL, related_name="pledges")
    deposit_date = models.DateField(null=True, blank=True)
    enwr_no = models.CharField(max_length=60, blank=True)
    repository = models.CharField(max_length=4, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    value_at_deposit = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    bank = models.CharField(max_length=120, blank=True)
    loan_amount = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True)
    interest_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    loan_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PLANNED, db_index=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def interest_so_far(self) -> Decimal:
        if not (self.loan_amount and self.interest_pct and self.loan_date):
            return Decimal(0)
        days = max(0, (timezone.localdate() - self.loan_date).days)
        return (self.loan_amount * self.interest_pct / 100 * days / 365).quantize(Decimal("1"))
