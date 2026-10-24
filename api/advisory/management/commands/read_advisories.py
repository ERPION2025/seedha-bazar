from django.core.management.base import BaseCommand

from advisory import imd, mkisan


class Command(BaseCommand):
    help = "Read the mKisan advisory feed now (and IMD district warnings, if IMD has whitelisted this server)."

    def add_arguments(self, parser):
        parser.add_argument("--imd", action="store_true", help="Also read IMD district warnings")

    def handle(self, *args, **opts):
        self.stdout.write(f"mKisan: {mkisan.sync()}")
        if opts["imd"]:
            self.stdout.write(f"IMD: {imd.sync()}")
