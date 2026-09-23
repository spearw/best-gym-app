"""The six athlete metrics the mockup shows (Metrics tab, onboarding, reminders).

Bodyweight and the three maxes are history rows; height and years training are
plain fields on the athlete. Weights arrive in someone's unit and are stored in kg."""

from django.db import transaction

from apps.exercises.models import Exercise
from apps.exercises.starter import ONBOARDING_MAX_KEYS

from . import units
from .models import BodyweightEntry, MaxEntry

MAX_KEYS = [key for key, _label in ONBOARDING_MAX_KEYS]

# key, label, kind ("weight", "height", "years")
METRICS = [
    ("bodyweight", "Bodyweight", "weight"),
    ("height_cm", "Height", "height"),
    ("sn", "Snatch 1RM", "weight"),
    ("cj", "Clean & Jerk 1RM", "weight"),
    ("bsq", "Back Squat 1RM", "weight"),
    ("years_training", "Years training", "years"),
]
METRIC_KEYS = [m[0] for m in METRICS]


def starter_exercises(gym):
    return {e.key: e for e in Exercise.objects.filter(gym=gym, key__in=MAX_KEYS)}


def current_metrics(athlete):
    """{key: {"value", "kg", "date", "source"}} for every metric; value None means not provided."""
    maxes = {entry.exercise.key: entry for entry in athlete.current_maxes().values()}
    bodyweight = athlete.current_bodyweight()
    result = {
        "bodyweight": _entry(bodyweight),
        "height_cm": {"value": athlete.height_cm, "date": None, "source": None},
        "years_training": {
            "value": athlete.get_years_training_display() if athlete.years_training else None,
            "date": None,
            "source": None,
        },
    }
    for key in MAX_KEYS:
        result[key] = _entry(maxes.get(key))
    return result


def _entry(row):
    if row is None:
        return {"value": None, "kg": None, "date": None, "source": None}
    return {"value": row.kg, "kg": row.kg, "date": row.date, "source": row.get_source_display()}


def missing_metrics(athlete):
    current = current_metrics(athlete)
    return [key for key in METRIC_KEYS if current[key]["value"] in (None, "")]


@transaction.atomic
def save_metrics(athlete, data, source, date=None, entry_units=None):
    """Save whichever metrics are present (not None/blank) in `data`, which uses
    METRIC_KEYS. Weights are in `entry_units` (default: the athlete's own unit)."""
    date = date or athlete.today()
    entry_units = entry_units or athlete.units
    if data.get("bodyweight") is not None:
        BodyweightEntry.objects.create(
            athlete=athlete, date=date, kg=units.to_kg(data["bodyweight"], entry_units), source=source
        )
    wanted = [k for k in MAX_KEYS if data.get(k) is not None]
    if wanted:
        exercises = starter_exercises(athlete.gym)
        for key in wanted:
            if key in exercises:
                MaxEntry.objects.create(
                    athlete=athlete,
                    exercise=exercises[key],
                    date=date,
                    kg=units.to_kg(data[key], entry_units),
                    reps=1,
                    source=source,
                )
    changed = []
    if data.get("height_cm") is not None:
        athlete.height_cm = data["height_cm"]
        changed.append("height_cm")
    if data.get("years_training"):
        athlete.years_training = data["years_training"]
        changed.append("years_training")
    if changed:
        athlete.save(update_fields=changed)
