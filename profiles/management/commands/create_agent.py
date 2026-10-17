from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, User, UserStatus
from accounts.phone import InvalidPhone, normalise_phone
from profiles.models import Organisation, OrgMembership


class Command(BaseCommand):
    help = "Create (or promote) an FPO/NGO agent for an organisation. The agent still signs in with a phone OTP."

    def add_arguments(self, parser):
        parser.add_argument("phone")
        parser.add_argument("org_code")

    def handle(self, *args, phone, org_code, **opts):
        try:
            phone = normalise_phone(phone)
        except InvalidPhone as e:
            raise CommandError(str(e))
        org = Organisation.objects.filter(code=org_code).first()
        if org is None:
            raise CommandError(f"No organisation with code {org_code}")
        user, created = User.objects.get_or_create(phone=phone, defaults={"role": Role.AGENT, "status": UserStatus.ACTIVE})
        if not created and user.role != Role.AGENT:
            raise CommandError("This number already belongs to a farmer or buyer account. Use a different number for the agent.")
        OrgMembership.objects.get_or_create(user=user, organisation=org)
        self.stdout.write(f"Agent {phone} linked to {org.name}. They can now sign in with an OTP.")
