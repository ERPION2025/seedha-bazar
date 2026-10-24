import csv
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from storage.models import Warehouse

COLUMNS = ["name", "operator", "wdra_reg_no", "repository", "state", "district", "address", "lat", "lon", "capacity_mt", "commodities", "phone"]


class Command(BaseCommand):
    help = ("Load WDRA-registered warehouses from a CSV (export the list from https://wdra.gov.in/registered-wh-public). "
            "Columns: " + ", ".join(COLUMNS) + ". Rows are matched on the WDRA registration number; safe to run again.")

    def add_arguments(self, parser):
        parser.add_argument("file")

    def handle(self, *args, **opts):
        n = 0
        with open(opts["file"], newline="") as fh:
            reader = csv.DictReader(fh)
            missing = {"name", "state", "district"} - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f"Missing columns: {', '.join(sorted(missing))}")
            for i, row in enumerate(reader, start=2):
                g = lambda k: (row.get(k) or "").strip()
                try:
                    defaults = {"name": g("name"), "operator": g("operator"), "repository": g("repository").lower()[:4], "state": g("state"), "district": g("district"),
                                "address": g("address"), "lat": float(g("lat")) if g("lat") else None, "lon": float(g("lon")) if g("lon") else None,
                                "capacity_mt": Decimal(g("capacity_mt")) if g("capacity_mt") else None, "commodities": g("commodities"), "phone": g("phone"), "verified": True}
                except ValueError as e:
                    raise CommandError(f"Line {i}: {e}")
                if g("wdra_reg_no"):
                    Warehouse.objects.update_or_create(wdra_reg_no=g("wdra_reg_no"), defaults=defaults)
                else:
                    Warehouse.objects.create(**defaults)
                n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} warehouses loaded."))
