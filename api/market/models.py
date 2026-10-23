from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

LISTING_DAYS = 30


def default_expiry():
    return timezone.now() + timedelta(days=LISTING_DAYS)


class Listing(models.Model):
    """Produce a farmer or an FPO offers for sale. Price is rupees per `unit`; price_per_quintal is kept for comparing with mandi rates."""

    class Status(models.TextChoices):
        ACTIVE = "active", "For sale"
        PAUSED = "paused", "Paused"
        SOLD = "sold", "Sold"
        HIDDEN = "hidden", "Hidden by Seedha Bazar"

    class Grade(models.TextChoices):
        A = "A", "Grade A"
        B = "B", "Grade B"
        C = "C", "Grade C"
        UNGRADED = "ungraded", "Not graded"

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings")
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="listings")
    source_cycle = models.ForeignKey("farmerbook.CropCycle", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    crop = models.CharField(max_length=60, db_index=True, help_text="Catalog key of what is sold: a crop, fresh produce, or a processed product")
    form = models.CharField(max_length=8, default="raw", db_index=True, help_text="raw, fresh or semi: set from the catalog")
    packaging = models.CharField(max_length=8, default="bulk", help_text="bulk (loose) or packed (retail packs); processed goods only")
    pack_size_g = models.PositiveIntegerField(null=True, blank=True, help_text="Grams (or ml) in one retail pack")
    brand = models.CharField(max_length=80, blank=True)
    fssai_no = models.CharField(max_length=20, blank=True, help_text="14-digit FSSAI licence or registration number, needed for packed food")
    shelf_life_days = models.PositiveIntegerField(null=True, blank=True)
    variety = models.CharField(max_length=60, blank=True)
    grade = models.CharField(max_length=10, choices=Grade.choices, default=Grade.UNGRADED)
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=8)
    bag_weight_kg = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=3)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    price_per_quintal = models.DecimalField(max_digits=12, decimal_places=2)
    state = models.CharField(max_length=60, db_index=True)
    district = models.CharField(max_length=80, db_index=True)
    village = models.CharField(max_length=120, blank=True)
    available_from = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    expires_at = models.DateTimeField(default=default_expiry)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_live(self) -> bool:
        return self.status == self.Status.ACTIVE and self.expires_at > timezone.now()

    @property
    def total_value(self) -> Decimal:
        return (self.quantity * self.price).quantize(Decimal("0.01"))

    @staticmethod
    def live():
        return Listing.objects.filter(status=Listing.Status.ACTIVE, expires_at__gt=timezone.now())


class Enquiry(models.Model):
    """A buyer's interest in one listing. Contact details stay hidden until the seller accepts ("unlock")."""

    class Status(models.TextChoices):
        NEW = "new", "New"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        CLOSED = "closed", "Closed"

    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="enquiries")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enquiries")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, help_text="In the listing's unit")
    offered_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Per the listing's unit")
    message = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlock_fee_paise = models.PositiveIntegerField(default=0, help_text="Charged to the buyer on unlock. 0 during the pilot; billing is not connected yet.")
    seller_seen_at = models.DateTimeField(null=True, blank=True)
    buyer_seen_at = models.DateTimeField(null=True, blank=True)
    last_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["listing", "buyer"], name="uniq_enquiry_per_buyer")]
        ordering = ["-created_at"]

    @property
    def unlocked(self) -> bool:
        return self.unlocked_at is not None


class EnquiryMessage(models.Model):
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    text = models.CharField(max_length=500)
    masked = models.BooleanField(default=False, help_text="Phone numbers or emails were hidden before the contact was unlocked")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
