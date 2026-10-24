import csv
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from insurance.models import Plan
from rates.crops import canonical_crop

COLUMNS = ["scheme", "state", "season", "crop", "districts", "farmer_share_pct", "sum_insured_per_ha", "cutoff_date", "insurer", "source"]


class Command(BaseCommand):
    help = ("Load a state's crop insurance notification from a CSV with columns: " + ", ".join(COLUMNS) +
            ". districts is a | separated list (blank = whole state); crop can be a name like 'Soybean'; dates are YYYY-MM-DD.")

    def add_arguments(self, parser):
        parser.add_argument("file")

    def handle(self, *args, **opts):
        made = 0
        with open(opts["file"], newline="") as fh:
            reader = csv.DictReader(fh)
            missing = set(COLUMNS) - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"Missing columns: {', '.join(sorted(missing))}")
            for i, row in enumerate(reader, start=2):
                crop = row["crop"].strip().lower()
                crop = canonical_crop(row["crop"]) or crop.replace(" ", "_")
                try:
                    Plan.objects.update_or_create(
                        scheme=row["scheme"].strip() or "pmfby", state=row["state"].strip(), season=row["season"].strip(), crop=crop,
                        defaults={"districts": [d.strip() for d in row["districts"].split("|") if d.strip()], "farmer_share_pct": Decimal(row["farmer_share_pct"]),
                                  "sum_insured_per_ha": Decimal(row["sum_insured_per_ha"]) if row["sum_insured_per_ha"].strip() else None,
                                  "cutoff_date": date.fromisoformat(row["cutoff_date"]) if row["cutoff_date"].strip() else None,
                                  "insurer": row["insurer"].strip(), "source": row["source"].strip(), "notified": True, "active": True})
                except Exception as e:
                    raise CommandError(f"Line {i}: {e}")
                made += 1
        self.stdout.write(self.style.SUCCESS(f"{made} notified plans loaded."))
