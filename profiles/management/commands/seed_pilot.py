from django.core.management.base import BaseCommand

from profiles.models import Organisation

PILOT = [
    ("naigarhi", "Naigarhi FPO"),
    ("gangeo", "Gangeo FPO"),
    ("mahamrutyunjay", "Mahamrutyunjay FPO"),
    ("sirmaur", "FPO Sirmaur Block"),
]


class Command(BaseCommand):
    help = "Create the four pilot FPOs (Rewa/Satna). They stay unverified until staff check them in the admin."

    def handle(self, *args, **opts):
        for code, name in PILOT:
            org, created = Organisation.objects.get_or_create(code=code, defaults={"name": name, "kind": "fpo", "verified": False})
            self.stdout.write(f"{'created' if created else 'exists '} {org.code}: {org.name} (verified={org.verified})")
        self.stdout.write("Set district, registration number and 'verified' in /admin/ once each FPO is confirmed.")
