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
# "10-12", "15–20 each", "20-30 min": a range counts its low end. "5-3-1" isn't a range.
_RANGE = re.compile(r"^(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)(?![\d.]|\s*[-–+]\s*\d)(.*)$")
_RIR = re.compile(r"^(\d+)(?:\s*[-–]\s*(\d+))?$")


def parse_rep_scheme(text):
    """(reps, duration_seconds) from what the coach typed. A range ("10-12", "20-30 min")
    counts its low end. Unrecognised text (e.g. "AMRAP", "20 m", "5-3-1") is kept for the
    athlete to read, with neither number set."""
    text = " ".join((text or "").split())
    if not text:
        return None, None
    if (m := _RANGE.match(text)) and Decimal(m.group(1)) < Decimal(m.group(2)):
        return parse_rep_scheme(m.group(1) + m.group(3))
    if _COMPLEX.match(text):
        return 1, None
    if m := _REPS.match(text):
        return int(m.group(1)), None
    if m := _TIME.match(text):
        amount, unit = Decimal(m.group(1)), m.group(2).lower()
        factor = 1 if unit.startswith("s") else 3600 if unit.startswith("h") else 60
        return None, int(amount * factor)
    return None, None


def parse_rir(text):
    """(low, high) from "2" or "1-2" (high is None for a single number). ValueError if it
    isn't one of those, or is above 10."""
    text = "".join((text or "").split())
    if not text:
        return None, None
    m = _RIR.match(text)
    if not m:
        raise ValueError(text)
    low, high = int(m.group(1)), int(m.group(2)) if m.group(2) else None
    if high == low:
        high = None
    if high is not None and high < low:
        low, high = high, low
    if max(low, high or 0) > 10:
        raise ValueError(text)
    return low, high


def rir_text(rir, rir_max):
    """'2', '1–2' or '' for an RIR target."""
    if rir is None:
        return ""
    return f"{rir}–{rir_max}" if rir_max is not None else str(rir)


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


def summary(rx, gym_units, set_overrides=None, custom=True):
    """The one-line description shown on the board: '5×3 @ 75% · RIR 2 · Tempo 3-1-0'.
    `custom=False` leaves out the custom fields (the athlete's day card). A warm-up drill
    is just its dose ("x 5 breaths")."""
    if getattr(rx, "warmup", False):
        return rx.rep_scheme or "warm-up"
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
        text += f" · RIR {rir_text(rx.rir, getattr(rx, 'rir_max', None))}"
    for field in (rx.custom_fields or []) if custom else []:
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

DOSE_FIELDS = [
    "sets",
    "rep_scheme",
    "reps",
    "duration_seconds",
    "load_value",
    "load_basis",
    "rir",
    "rir_max",
    "note",
    "custom_fields",
    "warmup",
]
# Where the item sits in its session: copied with the session, not with the exercise.
LAYOUT_FIELDS = ["section", "section_note", "superset"]
COPIED_FIELDS = DOSE_FIELDS + LAYOUT_FIELDS


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
        return {f: getattr(last, f) for f in DOSE_FIELDS}
    return new_dose(exercise)


def new_dose(exercise):
    """The default dose for an exercise nobody has prescribed yet. A warm-up drill is
    one set with nothing to fill in; the coach types its dose ("x 5 breaths")."""
    if exercise.warmup:
        return {"sets": 1, "rep_scheme": "", "reps": None, "duration_seconds": None, "warmup": True}
    dose = dict(DEFAULTS[exercise.measure])
    dose["reps"], dose["duration_seconds"] = parse_rep_scheme(dose["rep_scheme"])
    dose["load_basis"] = LoadBasis.NONE
    return dose


def session_items(session):
    """A program session's prescriptions or a template session's slots."""
    return session.prescriptions if hasattr(session, "prescriptions") else session.slots


def keep_warmups_first(session):
    """Renumber a session so its warm-up drills come first (keeping each group's order),
    so the board, the drag-and-drop positions and the player all agree."""
    items = list(session_items(session).order_by("order", "id"))
    ordered = sorted(items, key=lambda i: not i.warmup)
    for order, item in enumerate(ordered):
        if item.order != order:
            type(item).objects.filter(pk=item.pk).update(order=order)


def layout(items, get=lambda item: item):
    """Warm-ups, section headings and superset labels for a session's items, in order.
    Returns (warmups, rest): each rest entry is {"item", "section", "section_note",
    "label", "first"}, where `label` is "A1"/"A2" for a superset and "" otherwise, and
    `first` is False for the second and later exercises of a superset. Warm-ups come
    first whatever their order (services keep them first on the board too)."""
    items = list(items)
    warmups = [i for i in items if get(i).warmup]
    rest = [i for i in items if not get(i).warmup]
    groups = []
    for i, item in enumerate(rest):
        if i and get(item).superset:
            groups[-1].append(item)
        else:
            groups.append([item])
    entries = []
    for n, group in enumerate(groups):
        letter = chr(65 + n) if n < 26 else str(n + 1)
        for k, item in enumerate(group, start=1):
            rx = get(item)
            entries.append(
                {
                    "item": item,
                    "section": rx.section,
                    "section_note": rx.section_note,
                    "label": f"{letter}{k}" if len(group) > 1 else "",
                    "first": k == 1,
                }
            )
    return warmups, entries


def board_items(items, describe, get=lambda item: item):
    """A session's items flattened for a board, in order, each a dict with `describe(item)`
    merged in plus `heading` / `heading_note` (drawn above the card: "Warm-up" before the
    first drill, or a section), `label` ("A1") and `warmup`."""
    warmups, entries = layout(items, get)
    flat = []
    for i, item in enumerate(warmups):
        flat.append(
            {
                **describe(item),
                "warmup": True,
                "heading": "Warm-up" if i == 0 else "",
                "heading_note": "",
                "label": "",
            }
        )
    for e in entries:
        flat.append(
            {
                **describe(e["item"]),
                "warmup": False,
                "heading": e["section"],
                "heading_note": e["section_note"],
                "label": e["label"],
            }
        )
    return flat
