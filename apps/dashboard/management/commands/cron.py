"""The Render cron job's command, run hourly (render.yaml).

Every run: bring every coach's attention feed up to date (`nightly`), delete form videos
past their keep period, and send the morning digest to coaches whose gym has just
reached 7am.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.accounts.models import Coach
from apps.dashboard import digest
from apps.workouts import videos


class Command(BaseCommand):
    help = "Hourly jobs: alerts, form-video clean-up, morning digests."

    def handle(self, *args, **options):
        call_command("nightly", stdout=self.stdout)
        expired, abandoned = videos.expire()
        sent = sum(1 for coach in Coach.objects.select_related("user", "gym") if digest.send(coach))
        self.stdout.write(
            self.style.SUCCESS(
                f"cron: {expired} video(s) expired, {abandoned} unfinished upload(s) removed, "
                f"{sent} digest(s) sent"
            )
        )
