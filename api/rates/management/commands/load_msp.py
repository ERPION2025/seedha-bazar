import json
from pathlib import Path

from django.core.management.base import BaseCommand

from rates.models import MspPrice


class Command(BaseCommand):
    help = "Load government MSP rows from rates/data/msp.json (copied from the PIB notifications). Safe to run again."

    def handle(self, *args, **opts):
        data = json.loads((Path(__file__).resolve().parents[2] / "data" / "msp.json").read_text())
        n = 0
        for season in data["seasons"]:
            for crop, (name, price) in season["prices"].items():
                MspPrice.objects.update_or_create(crop=crop, name=name, season=season["season"], defaults={
                    "price_per_quintal": price, "announced_on": season["announced_on"], "source_url": season["source_url"]})
                n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} MSP rows loaded."))
