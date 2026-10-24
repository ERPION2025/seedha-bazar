import logging

from django.core.management.base import BaseCommand

from rates import worker


class Command(BaseCommand):
    help = "Keeps market rates fresh: fetches them about every 24 hours and then sends rate alerts. Run it as a separate always-on process."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Do one pass and exit")

    def handle(self, *args, once=False, **opts):
        logging.basicConfig(level=logging.INFO)
        if once:
            self.stdout.write("fetched" if worker.tick() else "not due")
        else:
            worker.loop()
