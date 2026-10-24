from django.conf import settings
from django.db import models
from django.utils import timezone


class Organisation(models.Model):
    class Kind(models.TextChoices):
        FPO = "fpo", "FPO"
        NGO = "ngo", "NGO"

    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=3, choices=Kind.choices, default=Kind.FPO)
    code = models.SlugField(max_length=20, unique=True, help_text="Short join code the FPO shares with members")
    registration_no = models.CharField(max_length=60, blank=True)
    state = models.CharField(max_length=60, default="Madhya Pradesh")
    district = models.CharField(max_length=80, blank=True)
    block = models.CharField(max_length=80, blank=True)
    verified = models.BooleanField(default=False, help_text="Set by Seedha Bazar staff after checking registration")
    lat = models.FloatField(null=True, blank=True, help_text="Office location, set by the FPO from its phone")
    lon = models.FloatField(null=True, blank=True)
    contact_name = models.CharField(max_length=120, blank=True)
    segments = models.JSONField(default=list, blank=True, help_text="Livelihoods its members follow")
    auto_approve_members = models.BooleanField(default=False, help_text="Farmers who join with this FPO's code are confirmed without a manual check")
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name


class OrgMembership(models.Model):
    class Role(models.TextChoices):
        AGENT = "agent", "Agent"
        ADMIN = "admin", "Org admin"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="org_memberships")
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.AGENT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "organisation"], name="uniq_member")]


class OrgStatus(models.TextChoices):
    NONE = "none", "Not linked"
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"


class FarmerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="farmer_profile")
    name = models.CharField(max_length=120, blank=True)
    village = models.CharField(max_length=120, blank=True)
    block = models.CharField(max_length=80, blank=True)
    district = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=60, default="Madhya Pradesh")
    land_acres = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    crops = models.JSONField(default=list, blank=True)
    segments = models.JSONField(default=list, blank=True, help_text="Livelihoods: crops, dairy, poultry, fisheries, apiculture, sericulture, piggery")
    contact_is_family = models.BooleanField(default=False, help_text="Phone belongs to a family member")
    family_contact_name = models.CharField(max_length=120, blank=True)
    organisation = models.ForeignKey(Organisation, null=True, blank=True, on_delete=models.SET_NULL, related_name="farmers")
    org_status = models.CharField(max_length=10, choices=OrgStatus.choices, default=OrgStatus.NONE)
    assisted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assisted_farmers")
    assisted_at = models.DateTimeField(null=True, blank=True)
    share_with_extension = models.BooleanField(null=True, blank=True, help_text="Farmer's choice to let the district KVK / research centre see their profile, crops and book. None = not asked yet.")
    discoverable = models.BooleanField(default=True, help_text="Verified buyers can see first name, village, crops and stock (never the phone number) and ask for produce")
    land_record_verified = models.BooleanField(default=False)
    documents_verified = models.BooleanField(default=False)
    level = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    LEVEL1_FIELDS = ("name", "village", "district")

    def basics_complete(self) -> bool:
        """Name, village, district, and for crop farmers their land and crops. Others need only their livelihoods."""
        if not all(getattr(self, f).strip() for f in self.LEVEL1_FIELDS):
            return False
        if self.segments and "crops" not in self.segments:
            return True
        return self.land_acres is not None and bool(self.crops)

    def compute_level(self) -> int:
        if not self.basics_complete():
            return 0
        if self.documents_verified:
            return 3
        if self.org_status == OrgStatus.CONFIRMED or self.land_record_verified:
            return 2
        return 1

    def save(self, *args, **kwargs):
        self.level = self.compute_level()
        super().save(*args, **kwargs)


class BuyerProfile(models.Model):
    class BusinessType(models.TextChoices):
        HOTEL = "hotel_restaurant", "Hotel / restaurant"
        GROCERY = "grocery", "Grocery / retail"
        CATERER = "caterer", "Caterer"
        PROCESSOR = "processor", "Processor / food company"
        DISTRIBUTOR = "distributor", "Wholesaler / distributor"
        OTHER = "other", "Other"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="buyer_profile")
    contact_name = models.CharField(max_length=120, blank=True)
    business_name = models.CharField(max_length=160, blank=True)
    business_type = models.CharField(max_length=20, choices=BusinessType.choices, blank=True)
    city = models.CharField(max_length=80, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    fssai = models.CharField(max_length=14, blank=True)
    documents_verified = models.BooleanField(default=False)
    level = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def compute_level(self) -> int:
        if not (self.business_name.strip() and self.business_type and self.city.strip()):
            return 0
        if self.documents_verified and (self.gstin or self.fssai):
            return 2
        return 1

    def save(self, *args, **kwargs):
        self.level = self.compute_level()
        super().save(*args, **kwargs)


class LinkStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class OrgLinkRequest(models.Model):
    """A farmer asks to be recognised as a member of an FPO/NGO."""

    farmer = models.ForeignKey(FarmerProfile, on_delete=models.CASCADE, related_name="link_requests")
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="link_requests")
    status = models.CharField(max_length=10, choices=LinkStatus.choices, default=LinkStatus.PENDING)
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
