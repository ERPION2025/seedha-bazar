from django.core.management.base import BaseCommand

from storage import wdra


class Command(BaseCommand):
    help = "Read WDRA's public list of registered warehouses into the database. Default: the states most overdue. --all reads every state (takes a few minutes)."

    def add_arguments(self, parser):
        parser.add_argument("states", nargs="*", help='State names as WDRA lists them, e.g. "Madhya Pradesh"')
        parser.add_argument("--all", action="store_true")

    def handle(self, *args, **opts):
        names = opts["states"] or None
        if opts["all"]:
            codes, _ = wdra.states_and_action(wdra.Session().get(wdra.settings.WDRA_LIST_URL))
            names = [n for n, c in codes.items() if c != "-1"]
        for r in wdra.sync_states(names):
            self.stdout.write(f"{r.state}: {'ok' if r.ok else 'FAILED ' + r.error} rows={r.rows} added={r.added} updated={r.updated} gone={r.gone}")
