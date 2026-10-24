from django.core.management.base import BaseCommand, CommandError

from accounts.errors import ApiError
from accounts.phone import InvalidPhone, normalise_phone
from profiles import services
from profiles.models import Organisation


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
        try:
            services.provision_agent(phone, org)
        except ApiError as e:
            raise CommandError(e.message)
        self.stdout.write(f"Agent {phone} linked to {org.name}. They can now sign in with an OTP.")
