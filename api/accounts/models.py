import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.conf import settings
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


class SitePolicy(models.Model):
    """User policies staff can change in the console. There is one row; `current()` creates it with the defaults."""

    max_sessions = models.PositiveSmallIntegerField(default=2, help_text="Most devices a person can be signed in on at once. Signing in on one more signs out the oldest.")
    session_days = models.PositiveSmallIntegerField(default=30, help_text="Days before a person must sign in again")
    facebook_login = models.BooleanField(default=False, help_text="Show 'Continue with Facebook' on the sign-in page (needs FACEBOOK_APP_ID and FACEBOOK_APP_SECRET)")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls) -> "SitePolicy":
        obj = cls.objects.order_by("pk").first()
        return obj or cls.objects.create()


class LoginSession(models.Model):
    """One signed-in browser or phone. Kept after sign-out for the record."""

    class Method(models.TextChoices):
        OTP = "otp", "Phone code"
        FACEBOOK = "facebook", "Facebook"
        EXISTING = "existing", "Signed in before session records began"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_sessions")
    session_key = models.CharField(max_length=64, db_index=True)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.OTP)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=20, blank=True, help_text="logout, limit (too many devices), staff, expired")

    class Meta:
        ordering = ["-created_at"]


class SocialLogin(models.Model):
    """A Facebook (or later another provider) account linked to a Seedha Bazar user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_logins")
    provider = models.CharField(max_length=20, default="facebook")
    uid = models.CharField(max_length=64)
    name = models.CharField(max_length=160, blank=True)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "uid"], name="uniq_social_uid")]
