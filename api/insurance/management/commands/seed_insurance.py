from django.core.management.base import BaseCommand

from insurance import rules
from insurance.models import Plan


class Command(BaseCommand):
    help = "Load the national premium rules (same in every state). Safe to run again."

    def handle(self, *args, **opts):
        made = 0
        for scheme, season, group, share in rules.NATIONAL:
            _, created = Plan.objects.get_or_create(scheme=scheme, state="", season=season, group=group, crop="",
                                                    defaults={"farmer_share_pct": share, "risks": rules.RISKS[scheme], "notified": False,
                                                              "source": "National PMFBY / RWBCIS premium caps for farmers"})
            made += created
        self.stdout.write(self.style.SUCCESS(f"National insurance rules: {made} new."))
