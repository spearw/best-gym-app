"""Nightly job run by the Render cron service (render.yaml, schedule 03:00 UTC).

Brings every coach's attention feed up to date: programs running out, missing
metrics, missed sessions and PRs waiting (apps/dashboard/alerts.py). The same checks
also run whenever a coach opens the dashboard, so this mainly keeps the sidebar
count right for coaches who haven't looked yet. The email digest is phase 8.
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import Coach
from apps.dashboard import alerts


class Command(BaseCommand):
    help = "Nightly maintenance: bring every coach's attention feed up to date."

    def handle(self, *args, **options):
        coaches = Coach.objects.select_related("user", "gym")
        for coach in coaches:
            alerts.sync_coach(coach)
        self.stdout.write(self.style.SUCCESS(f"nightly: synced alerts for {coaches.count()} coach(es)"))
