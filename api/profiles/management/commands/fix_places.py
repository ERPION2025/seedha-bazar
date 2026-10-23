from django.core.management.base import BaseCommand

from extension import geo
from profiles.models import FarmerProfile


class Command(BaseCommand):
    help = "Correct farmer profiles whose district is not in their state (when the district exists in exactly one state)."

    def handle(self, *args, **opts):
        fixed = 0
        for fp in FarmerProfile.objects.exclude(district=""):
            ok, other = geo.check_place(fp.state, fp.district)
            if not ok and other:
                self.stdout.write(f"  {fp.user.phone}: {fp.district} is in {other}, not {fp.state}")
                fp.state = other
                fp.save(update_fields=["state"])
                fixed += 1
        self.stdout.write(self.style.SUCCESS(f"{fixed} profiles corrected."))
