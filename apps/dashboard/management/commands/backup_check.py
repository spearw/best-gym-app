"""Print row counts and the newest records of the main tables, to compare a restored
backup against the live database (docs/OPERATIONS.md, "Backups")."""

from django.apps import apps
from django.core.management.base import BaseCommand

TABLES = [
    "accounts.Gym",
    "accounts.Coach",
    "accounts.Athlete",
    "programs.Program",
    "programs.Prescription",
    "workouts.SessionLog",
    "workouts.SetLog",
    "workouts.FormVideo",
    "messaging.Message",
    "library.Template",
]


class Command(BaseCommand):
    help = "Row counts and newest records, for checking a restored backup."

    def handle(self, *args, **options):
        for label in TABLES:
            model = apps.get_model(label)
            self.stdout.write(f"{label:28} {model.objects.count():>8}")
        SessionLog = apps.get_model("workouts.SessionLog")
        Message = apps.get_model("messaging.Message")
        newest_session = (
            SessionLog.objects.order_by("-finished_at").values_list("finished_at", flat=True).first()
        )
        newest_message = Message.objects.order_by("-sent_at").values_list("sent_at", flat=True).first()
        self.stdout.write(f"newest finished session: {newest_session}")
        self.stdout.write(f"newest message:          {newest_message}")
