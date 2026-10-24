from django.core.management.base import BaseCommand

from rates import ingest


class Command(BaseCommand):
    help = "Fetch today's mandi prices from the configured free public sources. Run it daily (the worker does this for you)."

    def handle(self, *args, **opts):
        for entry in ingest.run_update():
            style = self.style.SUCCESS if entry.status == "ok" else self.style.WARNING
            self.stdout.write(style(f"{entry.source}: {entry.status} fetched={entry.rows_fetched} saved={entry.rows_saved} latest={entry.latest_date} {entry.message}"))
