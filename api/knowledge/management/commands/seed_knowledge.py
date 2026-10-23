from django.core.management.base import BaseCommand

from knowledge import sources
from knowledge.models import Scheme
from knowledge.schemes_data import SCHEMES


class Command(BaseCommand):
    help = "Load the starter schemes and the default news sources. Safe to run again: it never overwrites what staff edited in the admin."

    def handle(self, *args, **opts):
        made = 0
        for i, s in enumerate(SCHEMES):
            data = {k: v for k, v in s.items() if k != "slug"}
            _, created = Scheme.objects.get_or_create(slug=s["slug"], defaults={**data, "sort": 10 * (i + 1)})
            made += created
        self.stdout.write(self.style.SUCCESS(f"Schemes: {made} new. News sources: {sources.seed()} new."))
