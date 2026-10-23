from django.core.management.base import BaseCommand

from issues import services


class Command(BaseCommand):
    help = "Delete voice notes and photos older than the keep period (default 180 days). The written text stays."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=services.KEEP_MEDIA_DAYS)

    def handle(self, *args, **opts):
        self.stdout.write(self.style.SUCCESS(f"Removed {services.purge_media(opts['days'])} old files."))
