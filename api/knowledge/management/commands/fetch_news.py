from django.core.management.base import BaseCommand

from knowledge import engine, sources


class Command(BaseCommand):
    help = "Read the news and video feeds now. The worker does this every few hours by itself."

    def add_arguments(self, parser):
        parser.add_argument("--source", type=int, help="Only this source id")
        parser.add_argument("--seed", action="store_true", help="Create the default sources first")

    def handle(self, *args, **opts):
        if opts["seed"] or not engine.Source.objects.exists():
            self.stdout.write(f"Default sources: {sources.seed()} new.")
        out = engine.run_all(opts["source"])
        self.stdout.write(self.style.SUCCESS(f"Read {out['sources']} sources: {out['added']} new items, {out['failed']} failed, {out['pruned']} old removed."))
        for s in engine.Source.objects.filter(last_error__gt=""):
            self.stdout.write(self.style.WARNING(f"  {s.name}: {s.last_error}"))
