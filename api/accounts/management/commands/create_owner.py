import secrets

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, User, UserStatus
from accounts.phone import InvalidPhone, normalise_phone


class Command(BaseCommand):
    help = ("Create (or reset) the owner of the Seedha Bazar console: full rights, password sign-in at /console/login/ and /admin/. "
            "Without --password a strong one is made and printed once.")

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", default="")

    def handle(self, *args, **o):
        try:
            phone = normalise_phone(o["phone"])
        except InvalidPhone:
            raise CommandError("Enter a valid 10-digit Indian mobile number")
        email = o["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(phone=phone).exists():
            raise CommandError("This email is already used by another account.")
        u = User.objects.filter(phone=phone).first()
        if u is not None and u.role not in (Role.ADMIN,) and not u.is_staff:
            raise CommandError(f"{phone} is a {u.role} account. Use another number for the owner.")
        password = o["password"] or secrets.token_urlsafe(12)
        if len(password) < 10:
            raise CommandError("Use at least 10 characters.")
        u = u or User(phone=phone)
        u.email, u.role, u.status, u.is_staff, u.is_superuser = email, Role.ADMIN, UserStatus.ACTIVE, True, True
        u.set_password(password)
        u.save()
        self.stdout.write(self.style.SUCCESS(f"Owner ready. Sign in at /console/login/ with {phone} or {email}"))
        if not o["password"]:
            self.stdout.write(f"Password (shown once, change it after signing in): {password}")
