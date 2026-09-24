"""Load the mockup's demo data. Grows with every phase (docs/BUILD_PLAN.md, "Seed data").

Phase 9 adds a real client's program style, anonymised (_seed_meso.py): Riley, in pounds,
on a 4-day RIR block with warm-up drills, sections, supersets and a program note.
Phase 7 adds the mockup's habits (seed_habits in _seed_sessions.py).
Phase 5 adds the mockup's templates, saved weeks and saved sessions (_seed_library.py).
Phase 4 adds the mockup's logged sessions and check-ins (_seed_sessions.py).
Phase 1: Iron Ridge Weightlifting, coach Dana, six athletes with their profiles,
bodyweight history and maxes, and the starter exercise library.
Safe to run repeatedly: rows are updated, and the demo athletes' measurement
history is rebuilt relative to today so the numbers always look recent.
"""

import datetime
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import (
    Athlete,
    BodyweightEntry,
    Coach,
    Gym,
    MaxEntry,
    MeasurementSource,
    User,
)
from apps.exercises.starter import install_pack
from apps.workouts.models import CheckinQuestion, copy_defaults_to, install_default_questions

from ._seed_library import seed_library
from ._seed_meso import seed_meso
from ._seed_programs import seed_programs
from ._seed_sessions import seed_habits, seed_sessions

TZ = "America/New_York"
GYM_NAME = "Iron Ridge Weightlifting"
COACH = ("dana@ironridge.example", "Dana Whitfield", "Head coach")

# From the mockup's CLIENTS: class, competition, height, years, current bodyweight,
# and PRs as (exercise key, kg, days ago). None means "not provided" in the mockup.
ATHLETES = [
    {
        "email": "maya@ironridge.example",
        "name": "Maya Torres",
        "class": "64 kg",
        "comp": ("Nationals", (10, 17)),
        "height": "168",
        "years": "3-5",
        "bodyweight_history": [
            (2, "63.8"),
            (5, "63.9"),
            (9, "64.1"),
            (12, "64.2"),
            (16, "64.6"),
            (23, "64.9"),
            (33, "65.3"),
            (44, "65.6"),
            (55, "65.8"),
        ],
        "maxes": [("sn", "82", 12), ("cj", "104", 26), ("bsq", "135", 40)],
    },
    {
        "email": "jonas@ironridge.example",
        "name": "Jonas Kim",
        "class": "89 kg",
        "comp": ("Regionals", (11, 8)),
        "height": "181",
        "years": "5+",
        "bodyweight_history": [(1, "88.2")],
        "maxes": [("sn", "112", 60), ("cj", "138", 60), ("bsq", "190", 33)],
    },
    {
        "email": "priya@ironridge.example",
        "name": "Priya Nair",
        "class": "55 kg",
        "comp": None,
        "height": "158",
        "years": "1-3",
        "bodyweight_history": [(1, "54.6")],
        "maxes": [("sn", "55", 9), ("cj", "70", 9), ("bsq", "92", 20)],
    },
    {
        "email": "marcus@ironridge.example",
        "name": "Marcus Webb",
        "class": "102 kg",
        "comp": ("Masters", (12, 5)),
        "height": "188",
        "years": "5+",
        "bodyweight_history": [],  # not provided
        "maxes": [("sn", "95", 120), ("bsq", "160", 90)],
    },  # C&J not provided
    {
        "email": "lena@ironridge.example",
        "name": "Lena Okafor",
        "class": "71 kg",
        "comp": None,
        "height": "172",
        "years": "",  # years not provided
        "bodyweight_history": [(2, "70.4")],
        "maxes": [("sn", "68", 31), ("cj", "85", 31), ("bsq", "110", 45)],
    },
    {
        "email": "theo@ironridge.example",
        "name": "Theo Lindqvist",
        "class": "109+ kg",
        "comp": ("Nationals", (10, 17)),
        "height": "193",
        "years": "5+",
        "bodyweight_history": [(1, "118.5")],
        "maxes": [("sn", "130", 75), ("cj", "162", 75), ("bsq", "230", 50)],
    },
]


def _next_date(today, month, day):
    candidate = datetime.date(today.year, month, day)
    return candidate if candidate >= today else datetime.date(today.year + 1, month, day)


class Command(BaseCommand):
    help = "Create or refresh the mockup's demo data (Iron Ridge, Dana the coach, six athletes)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-empty",
            action="store_true",
            help="Do nothing if the demo gym already exists (the free-tier trial seeds on start-up).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_PASSWORD:
            raise CommandError("Set DEMO_PASSWORD: demo users on a public site need their own password.")
        if options["if_empty"] and Gym.objects.filter(name=GYM_NAME).exists():
            self.stdout.write("Demo gym already there; not reseeding.")
            return
        gym, _ = Gym.objects.update_or_create(name=GYM_NAME, defaults={"timezone": TZ, "units": "kg"})
        exercises = install_pack(gym, "weightlifting")
        install_default_questions(gym)
        today = gym.today()

        email, name, title = COACH
        coach_user = self._user(email, name, is_staff=True)
        coach, _ = Coach.objects.update_or_create(user=coach_user, defaults={"gym": gym, "title": title})

        athletes_by_email = {}
        for spec in ATHLETES:
            user = self._user(spec["email"], spec["name"])
            comp_name, comp_date = "", None
            if spec["comp"]:
                comp_name = spec["comp"][0]
                comp_date = _next_date(today, *spec["comp"][1])
            athlete, _ = Athlete.objects.update_or_create(
                user=user,
                defaults={
                    "coach": coach,
                    "gym": gym,
                    "weight_class": spec["class"],
                    "competition_name": comp_name,
                    "competition_date": comp_date,
                    "height_cm": Decimal(spec["height"]) if spec["height"] else None,
                    "years_training": spec["years"],
                    "units": "kg",
                    "archived_at": None,
                },
            )
            athlete.bodyweights.all().delete()
            BodyweightEntry.objects.bulk_create(
                [
                    BodyweightEntry(
                        athlete=athlete,
                        date=today - datetime.timedelta(days=d),
                        kg=Decimal(kg),
                        source=MeasurementSource.ATHLETE,
                    )
                    for d, kg in spec["bodyweight_history"]
                ]
            )
            athlete.maxes.all().delete()
            MaxEntry.objects.bulk_create(
                [
                    MaxEntry(
                        athlete=athlete,
                        exercise=exercises[key],
                        date=today - datetime.timedelta(days=d),
                        kg=Decimal(kg),
                        reps=1,
                        source=MeasurementSource.SESSION,
                    )
                    for key, kg, d in spec["maxes"]
                ]
            )
            if not CheckinQuestion.objects.for_athlete(athlete).filter(archived=False).exists():
                copy_defaults_to(athlete)
            athletes_by_email[spec["email"]] = athlete
            self.stdout.write(f"athlete {spec['email']}")

        seed_programs(athletes_by_email, exercises, coach_user, today)
        seed_sessions(athletes_by_email, exercises, today)
        seed_library(gym, exercises, coach_user)
        seed_habits(athletes_by_email, today)
        seed_meso(gym, coach, coach_user, today)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {GYM_NAME}, coach {COACH[0]}, {len(ATHLETES) + 1} athletes, "
                f"{len(exercises)} exercises. New demo users' password is DEMO_PASSWORD."
            )
        )

    def _user(self, email, name, is_staff=False):
        user, created = User.objects.update_or_create(
            email=email,
            defaults={
                "name": name,
                "timezone": TZ,
                "is_staff": is_staff and settings.DEMO_STAFF,
                "is_superuser": is_staff and settings.DEMO_STAFF,
            },
        )
        if created:
            user.set_password(settings.DEMO_PASSWORD)
            user.save(update_fields=["password"])
        return user
