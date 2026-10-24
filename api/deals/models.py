"""Orders made to measure: a buyer asks a farmer or FPO for produce or a processed product (dried, flour, pulp...),
they agree the terms, both sign the agreement, the buyer pays an advance, the seller delivers, the buyer pays the rest."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Deal(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Request sent"
        NEGOTIATING = "negotiating", "Agreeing the terms"
        AGREED = "agreed", "Terms agreed, waiting for signatures"
        SIGNED = "signed", "Agreement signed, waiting for advance"
        ADVANCE_PAID = "advance_paid", "Advance paid, waiting for confirmation"
        IN_PROGRESS = "in_progress", "Being prepared"
        DISPATCHED = "dispatched", "Sent to the buyer"
        DELIVERED = "delivered", "Delivered, waiting for final payment"
        COMPLETED = "completed", "Completed"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"

    OPEN = ("requested", "negotiating", "agreed", "signed", "advance_paid", "in_progress", "dispatched", "delivered")

    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deals_bought")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deals_sold", help_text="The farmer, or the FPO agent who handles it")
    organisation = models.ForeignKey("profiles.Organisation", null=True, blank=True, on_delete=models.SET_NULL, related_name="deals")
    product = models.CharField(max_length=60, help_text="Catalog key of what is ordered")
    source_crop = models.CharField(max_length=60, blank=True, help_text="For processed goods: the crop it is made from")
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=8, default="kg")
    quality = models.CharField(max_length=300, blank=True)
    packaging = models.CharField(max_length=8, default="bulk")
    pack_size_g = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Rupees per unit")
    advance_pct = models.PositiveSmallIntegerField(default=20)
    delivery_by = models.DateField()
    delivery_place = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    agreed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    received_quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    buyer_seen_at = models.DateTimeField(null=True, blank=True)
    seller_seen_at = models.DateTimeField(null=True, blank=True)
    buyer_rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Buyer's rating of the seller, 1-5")
    seller_rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Seller's rating of the buyer, 1-5")

    class Meta:
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def total(self) -> Decimal:
        return (self.quantity * self.price).quantize(Decimal("1"))

    @property
    def advance_amount(self) -> Decimal:
        return (self.total * self.advance_pct / 100).quantize(Decimal("1"))

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN


class Offer(models.Model):
    """One round of terms. The newest offer is on the table; the other side can accept it or counter."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="offers")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    side = models.CharField(max_length=6, choices=[("buyer", "Buyer"), ("seller", "Seller")])
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    advance_pct = models.PositiveSmallIntegerField()
    delivery_by = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]


class Agreement(models.Model):
    """The agreed terms as signed. `doc_hash` fingerprints the exact text, so any later change would show."""

    deal = models.OneToOneField(Deal, on_delete=models.CASCADE, related_name="agreement")
    terms = models.JSONField()
    text = models.TextField()
    doc_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)
    buyer_signed_at = models.DateTimeField(null=True, blank=True)
    buyer_sign_ip = models.GenericIPAddressField(null=True, blank=True)
    buyer_sign_agent = models.CharField(max_length=200, blank=True)
    seller_signed_at = models.DateTimeField(null=True, blank=True)
    seller_signer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    seller_sign_ip = models.GenericIPAddressField(null=True, blank=True)
    seller_sign_agent = models.CharField(max_length=200, blank=True)
    method = models.CharField(max_length=20, default="otp", help_text="otp: each party confirmed with a one-time code sent to their phone")

    @property
    def fully_signed(self) -> bool:
        return bool(self.buyer_signed_at and self.seller_signed_at)


class Payment(models.Model):
    class Kind(models.TextChoices):
        ADVANCE = "advance", "Advance"
        BALANCE = "balance", "Balance"

    class Method(models.TextChoices):
        UPI = "upi", "UPI"
        BANK = "bank", "Bank transfer (NEFT/RTGS/IMPS)"
        CHEQUE = "cheque", "Cheque"
        CASH = "cash", "Cash"

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="payments")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=0)
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.UPI)
    reference = models.CharField(max_length=80, blank=True, help_text="UTR or cheque number")
    marked_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    disputed = models.BooleanField(default=False)
    note = models.CharField(max_length=300, blank=True)
    gateway = models.CharField(max_length=30, default="offline", help_text="offline: paid outside the app and confirmed by both sides")
    gateway_ref = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["marked_at"]


class DealEvent(models.Model):
    """The timeline both sides see: messages, progress updates, dispatch, delivery, problems."""

    class Kind(models.TextChoices):
        MESSAGE = "message", "Message"
        PROGRESS = "progress", "Progress"
        DISPATCH = "dispatch", "Dispatched"
        DELIVERY = "delivery", "Delivered"
        ISSUE = "issue", "Problem"
        SYSTEM = "system", "Update"

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="events")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MESSAGE)
    text = models.CharField(max_length=500)
    masked = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
