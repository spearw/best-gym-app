"""Load the mockup's demo data. Grows with every phase (docs/BUILD_PLAN.md, "Seed data").

Phase 0: the demo users only. Coach/Athlete profiles, exercises, programs and
session logs are added as their models land in phases 1 to 4.
Safe to run repeatedly: existing rows are updated, not duplicated.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User

DEMO_PASSWORD = "demo-password-123"

DEMO_USERS = [
    # (email, name, timezone, is_staff)
    ("dana@ironridge.example", "Dana Whitfield", "America/New_York", True),
    ("maya@ironridge.example", "Maya Torres", "America/New_York", False),
    ("jonas@ironridge.example", "Jonas Kim", "America/New_York", False),
    ("priya@ironridge.example", "Priya Nair", "America/New_York", False),
    ("marcus@ironridge.example", "Marcus Webb", "America/New_York", False),
    ("lena@ironridge.example", "Lena Okafor", "America/New_York", False),
    ("theo@ironridge.example", "Theo Lindqvist", "America/New_York", False),
]


class Command(BaseCommand):
    help = "Create or refresh the mockup's demo data (Dana the coach, Maya and five other athletes)."

    @transaction.atomic
    def handle(self, *args, **options):
        for email, name, tz, is_staff in DEMO_USERS:
            user, created = User.objects.update_or_create(
                email=email,
                defaults={"name": name, "timezone": tz, "is_staff": is_staff, "is_superuser": is_staff},
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            self.stdout.write(f"{'created' if created else 'updated'} {email}")
        self.stdout.write(
            self.style.SUCCESS(f"Demo data ready. Password for new demo users: {DEMO_PASSWORD}")
        )
