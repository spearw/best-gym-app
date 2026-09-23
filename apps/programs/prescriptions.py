"""Reading and describing prescriptions: parsing the rep scheme a coach types,
formatting loads in someone's unit, and the default dose for a newly added exercise."""

import re
from decimal import Decimal

from apps.accounts import units
from apps.exercises.models import Measure

from .models import LoadBasis

_NUMBER = r"(\d+(?:\.\d+)?)"
# "m" is metres, not minutes: minutes need "min". Distances are kept as text for the athlete.
_TIME = re.compile(rf"^{_NUMBER}\s*(s|sec|secs|seconds?|min|mins|minutes?|h|hr|hrs|hours?)$", re.I)
_REPS = re.compile(r"^(\d+)(?:\s*(?:/\s*\w+|per\s+\w+|each(?:\s+\w+)?))?$", re.I)  # "5", "8/leg", "10 each"
_COMPLEX = re.compile(r"^\d+(?:\s*\+\s*\d+)+$")  # "1+1", "2+1+1": one rep of the complex


def parse_rep_scheme(text):
    """(reps, duration_seconds) from what the coach typed. Unrecognised text (e.g. "AMRAP",
    "20 m", "5-3-1") is kept for the athlete to read, with neither number set."""
    text = " ".join((text or "").split())
    if not text:
        return None, None
    if _COMPLEX.match(text):
        return 1, None
    if m := _REPS.match(text):
        return int(m.group(1)), None
    if m := _TIME.match(text):
        amount, unit = Decimal(m.group(1)), m.group(2).lower()
        factor = 1 if unit.startswith("s") else 3600 if unit.startswith("h") else 60
        return None, int(amount * factor)
    return None, None


def load_text(load_basis, load_value, gym_units):
    """'75%', 'RPE 8', '100 kg', 'BW' or '' for a prescription's load, in the viewer's unit."""
    if load_basis == LoadBasis.BODYWEIGHT:
        return "BW"
    if load_value is None or load_basis == LoadBasis.NONE:
        return ""
    value = Decimal(load_value).normalize()
    if load_basis == LoadBasis.PERCENT:
        return f"{format(value, 'f')}%"
    if load_basis == LoadBasis.RPE:
        return f"RPE {format(value, 'f')}"
    return units.display(load_value, gym_units)


def summary(rx, gym_units, set_overrides=None):
    """The one-line description shown on the board: '5×3 @ 75% · RIR 2 · Tempo 3-1-0'."""
    overrides = list(rx.set_overrides.all()) if set_overrides is None else set_overrides
    if overrides:
        parts = []
        for s in overrides:
            reps = s.rep_scheme or rx.rep_scheme
            load = load_text(
                rx.load_basis, s.load_value if s.load_value is not None else rx.load_value, gym_units
            )
            parts.append(f"{reps}@{load}" if load else reps)
        text = f"{len(overrides)} sets: " + ", ".join(parts)
    else:
        text = (
            f"{rx.sets}×{rx.rep_scheme}" if rx.rep_scheme else f"{rx.sets} set{'s' if rx.sets != 1 else ''}"
        )
        load = load_text(rx.load_basis, rx.load_value, gym_units)
        if load:
            text += f" @ {load}"
    if rx.rir is not None:
        text += f" · RIR {rx.rir}"
    for field in rx.custom_fields or []:
        text += f" · {field.get('key', '')} {field.get('value', '')}".rstrip()
    return text


def suggested_weight(rx, athlete, gym_units):
    """'≈ 62.5 kg of Snatch max 82 kg' for a percentage load, or None."""
    if rx.load_basis != LoadBasis.PERCENT or rx.load_value is None:
        return None
    source = rx.exercise.max_source
    entry = athlete.current_max(source)
    if entry is None:
        return None
    kg = entry.kg * Decimal(rx.load_value) / 100
    return f"≈ {units.display(kg, gym_units)} of {source.name} max {units.display(entry.kg, gym_units)}"


DEFAULTS = {
    Measure.REPS: {"sets": 3, "rep_scheme": "5"},
    Measure.TIME: {"sets": 1, "rep_scheme": "10 min"},
    Measure.DISTANCE: {"sets": 3, "rep_scheme": "20 m"},
}

COPIED_FIELDS = [
    "sets",
    "rep_scheme",
    "reps",
    "duration_seconds",
    "load_value",
    "load_basis",
    "rir",
    "note",
    "custom_fields",
]


def default_dose(exercise, athlete):
    """How a newly added exercise starts: the way this athlete was last prescribed it,
    else a sensible default for how the exercise is measured."""
    from .models import Prescription

    last = (
        Prescription.objects.filter(exercise=exercise, session__day__week__program__athlete=athlete)
        .order_by("-session__day__date", "-id")
        .first()
    )
    if last is not None:
        return {f: getattr(last, f) for f in COPIED_FIELDS}
    dose = dict(DEFAULTS[exercise.measure])
    dose["reps"], dose["duration_seconds"] = parse_rep_scheme(dose["rep_scheme"])
    dose["load_basis"] = LoadBasis.NONE
    return dose
