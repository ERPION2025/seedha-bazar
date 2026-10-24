import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from catalog import odop
from catalog.models import DistrictProduct

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "odop.csv"


class Command(BaseCommand):
    help = "Load the One District One Product list (official PM-FME list, 713 districts). Safe to run again."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(DEFAULT))

    def handle(self, *args, **opts):
        made = changed = 0
        with open(opts["file"], newline="") as fh:
            for row in csv.DictReader(fh):
                obj, created = DistrictProduct.objects.update_or_create(
                    state=row["state"].strip(), district=row["district"].strip(),
                    defaults={"product": row["product"].strip(), "crops": odop.crops_for(row["product"])})
                made += created
                changed += not created
        self.stdout.write(self.style.SUCCESS(f"ODOP list loaded: {made} new, {changed} updated."))
