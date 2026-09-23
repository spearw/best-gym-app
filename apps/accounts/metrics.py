"""The athlete metrics shown at onboarding, on the coach's Metrics tab, in the
athlete header, and in reminder emails.

Three personal metrics are the same for every gym: bodyweight, height and years
training. After them come the gym's tracked lifts (Settings › Tracked lifts), in
the gym's order. Bodyweight and lift maxes are dated history rows; height and
years training are plain fields on the athlete. Weights arrive in someone's unit
and are stored in kg.

A lift metric's key is "lift_<exercise id>", so forms, URLs and saved data all
refer to the gym's own exercises rather than to fixed names.
"""

from dataclasses import dataclass

from django.db import transaction

from apps.exercises.models import Exercise, tracked_exercises

from . import units
from .models import BodyweightEntry, MaxEntry

LIFT_PREFIX = "lift_"


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    kind: str  # "weight", "height" or "years"
    exercise: Exercise | None = None


def lift_key(exercise):
    return f"{LIFT_PREFIX}{exercise.pk}"


def metric_specs(gym):
    lifts = [Metric(lift_key(e), f"{e.name} 1RM", "weight", e) for e in tracked_exercises(gym)]
    return [
        Metric("bodyweight", "Bodyweight", "weight"),
        Metric("height_cm", "Height", "height"),
        *lifts,
        Metric("years_training", "Years training", "years"),
    ]


def spec_for(gym, key):
    return next((m for m in metric_specs(gym) if m.key == key), None)


def current_metrics(athlete, specs=None):
    """{key: {"value", "kg", "date", "source"}} for every metric; value None means not provided."""
    specs = specs or metric_specs(athlete.gym)
    maxes = athlete.current_maxes()  # {exercise_id: MaxEntry}
    result = {}
    for m in specs:
        if m.key == "bodyweight":
            result[m.key] = _entry(athlete.current_bodyweight())
        elif m.key == "height_cm":
            result[m.key] = {"value": athlete.height_cm, "kg": None, "date": None, "source": None}
        elif m.key == "years_training":
            value = athlete.get_years_training_display() if athlete.years_training else None
            result[m.key] = {"value": value, "kg": None, "date": None, "source": None}
        else:
            result[m.key] = _entry(maxes.get(m.exercise.pk))
    return result


def _entry(row):
    if row is None:
        return {"value": None, "kg": None, "date": None, "source": None}
    return {"value": row.kg, "kg": row.kg, "date": row.date, "source": row.get_source_display()}


def missing_metrics(athlete, specs=None):
    specs = specs or metric_specs(athlete.gym)
    current = current_metrics(athlete, specs)
    return [m.key for m in specs if current[m.key]["value"] in (None, "")]


@transaction.atomic
def save_metrics(athlete, data, source, date=None, entry_units=None):
    """Save whichever metrics in `data` are present (not None/blank). Keys are metric
    keys; lift keys must name a tracked lift of the athlete's gym, others are ignored.
    Weights are in `entry_units` (default: the athlete's own unit)."""
    date = date or athlete.today()
    entry_units = entry_units or athlete.units
    if data.get("bodyweight") is not None:
        BodyweightEntry.objects.create(
            athlete=athlete, date=date, kg=units.to_kg(data["bodyweight"], entry_units), source=source
        )
    for m in metric_specs(athlete.gym):
        if m.exercise is not None and data.get(m.key) is not None:
            MaxEntry.objects.create(
                athlete=athlete,
                exercise=m.exercise,
                date=date,
                kg=units.to_kg(data[m.key], entry_units),
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
