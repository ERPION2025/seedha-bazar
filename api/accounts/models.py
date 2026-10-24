import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    FARMER = "farmer", "Farmer"
    BUYER = "buyer", "Buyer"
    AGENT = "agent", "FPO/NGO agent"
    AGRONOMIST = "agronomist", "Agronomist"
    ADMIN = "admin", "Admin"


class Language(models.TextChoices):
    HINDI = "hi", "Hindi"
    MARATHI = "mr", "Marathi"
    ENGLISH = "en", "English"


class UserStatus(models.TextChoices):
    PENDING = "pending", "Pending owner confirmation"
    ACTIVE = "active", "Active"
    DELETED = "deleted", "Deleted"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra):
        user = self.model(phone=phone, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", Role.ADMIN)
        extra.setdefault("status", UserStatus.ACTIVE)
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """The phone number is the account. No email, no password for farmers."""

    phone = models.CharField(max_length=20, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FARMER)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.HINDI)
    status = models.CharField(max_length=20, choices=UserStatus.choices, default=UserStatus.PENDING)
    created_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="created_users")
    consented_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=32, blank=True)
    pin_hash = models.CharField(max_length=128, blank=True)
    pin_failed = models.PositiveSmallIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []

    @property
    def is_active(self):  # Django auth hook
        return self.status != UserStatus.DELETED

    def __str__(self):
        return f"{self.phone} ({self.role})"


class Device(models.Model):
    """One signed-in phone. Refresh tokens are bound to a device and rotate on use."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=64)
    name = models.CharField(max_length=80, blank=True)
    refresh_hash = models.CharField(max_length=64, blank=True)
    prev_refresh_hash = models.CharField(max_length=64, blank=True)
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "device_id"], name="uniq_user_device")]

    @property
    def is_active(self):
        return self.revoked_at is None


class OtpChallenge(models.Model):
    phone = models.CharField(max_length=20, db_index=True)
    code_hash = models.CharField(max_length=64)
    channel = models.CharField(max_length=10, default="sms")
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField()
    wrong_attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=60, db_index=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
