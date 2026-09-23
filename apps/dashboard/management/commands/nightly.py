"""Nightly job run by the Render cron service (render.yaml, schedule 03:00 UTC).

Phase 6 adds the real work: program-ending notifications (deduplicated), missed-day
alerts and the coach digest. Until then it checks the database connection so a
misconfigured cron job fails loudly.
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Nightly maintenance: notifications and digests (phase 6)."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        self.stdout.write(self.style.SUCCESS("nightly: database reachable, no jobs yet"))
