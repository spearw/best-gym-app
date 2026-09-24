"""Starting, logging and finishing a session. Views in views.py stay thin.

When a session starts, each prescription is copied into a SessionExercise with a JSON
snapshot of the dose (and its per-set overrides, and the working max at the time), so
"asked for" never changes when the coach edits the day afterwards.
"""

from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import units
from apps.programs.models import LoadBasis
from apps.programs.prescriptions import layout

from . import prs
from .models import SessionExercise, SessionLog, SetLog

PLATE_STEP = {"kg": Decimal("0.5"), "lb": Decimal("2.5")}


def _dec(value):
    return None if value is None else str(value)


def snapshot(rx, athlete):
    """What the coach asked for, frozen when the session starts."""
    source = rx.exercise.max_source
    working_max = athlete.current_max(source) if rx.load_basis == LoadBasis.PERCENT else None
    return {
        "exercise": rx.exercise.name,
        "sets": rx.sets,
        "rep_scheme": rx.rep_scheme,
        "reps": rx.reps,
        "duration_seconds": rx.duration_seconds,
        "load_value": _dec(rx.load_value),
        "load_basis": rx.load_basis,
        "rir": rx.rir,
        "rir_max": rx.rir_max,
        "note": rx.note,
        "custom_fields": list(rx.custom_fields or []),
        "warmup": rx.warmup,
        "section": rx.section,
        "section_note": rx.section_note,
        "superset": rx.superset,
        "set_overrides": [
            {
                "set_number": s.set_number,
                "rep_scheme": s.rep_scheme,
                "reps": s.reps,
                "load_value": _dec(s.load_value),
            }
            for s in rx.set_overrides.all()
        ],
        "max_exercise": source.name if working_max else None,
        "max_kg": _dec(working_max.kg) if working_max else None,
    }


def prescribed(se):
    """The snapshot as an object prescriptions.summary() can read; None if unprogrammed."""
    data = se.prescribed or {}
    if not data:
        return None
    dec = lambda v: None if v in (None, "") else Decimal(v)  # noqa: E731
    return SimpleNamespace(
        sets=data.get("sets") or 1,
        rep_scheme=data.get("rep_scheme", ""),
        reps=data.get("reps"),
        duration_seconds=data.get("duration_seconds"),
        load_value=dec(data.get("load_value")),
        load_basis=data.get("load_basis", LoadBasis.NONE),
        rir=data.get("rir"),
        rir_max=data.get("rir_max"),
        note=data.get("note", ""),
        custom_fields=data.get("custom_fields") or [],
        warmup=bool(data.get("warmup")),
        section=data.get("section", ""),
        section_note=data.get("section_note", ""),
        superset=bool(data.get("superset")),
        overrides=[
            SimpleNamespace(
                set_number=o["set_number"],
                rep_scheme=o.get("rep_scheme", ""),
                reps=o.get("reps"),
                load_value=dec(o.get("load_value")),
            )
            for o in data.get("set_overrides") or []
        ],
        max_exercise=data.get("max_exercise"),
        max_kg=dec(data.get("max_kg")),
    )


def plate_round(kg, unit):
    """A kg value shown in `unit`, rounded to the nearest plate step (display only)."""
    step = PLATE_STEP[unit]
    value = (units.from_kg(kg, unit) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    # normalize() alone would write 80 as "8E+1".
    return value.quantize(Decimal("1")) if value == value.to_integral_value() else value.normalize()


def target_kg(p, load_value):
    """The load a set is worked at in kg, where the prescription says: a % of the
    snapshot's working max, or a fixed weight. None otherwise (RPE, bodyweight, none)."""
    if load_value is None:
        return None
    if p.load_basis == LoadBasis.PERCENT:
        return p.max_kg * load_value / 100 if p.max_kg else None
    if p.load_basis == LoadBasis.WEIGHT:
        return load_value
    return None


def session_name(exercise_names):
    """The mockup's name for an unnamed session: 'Snatch + Back Squat + 2 more'."""
    names = list(exercise_names)
    text = " + ".join(names[:2])
    return text + (f" + {len(names) - 2} more" if len(names) > 2 else "")


def planned_sets(se):
    """Sets the coach asked for (0 for a warm-up drill, which is ticked off, not logged)."""
    p = prescribed(se)
    if p is None or se.warmup:
        return 0
    return len(p.overrides) or p.sets


def _placement(se):
    p = prescribed(se)
    return SimpleNamespace(
        warmup=se.warmup,
        superset=bool(p and p.superset),
        section=p.section if p else "",
        section_note=p.section_note if p else "",
    )


def steps(exercises):
    """The player's screens for a session, in order: the warm-up checklist (if the coach
    set one), then one screen per exercise, with a superset's exercises together.
    Each step is {"warmup": bool, "items": [SessionExercise], "labels": ["A1", ...],
    "section": str, "section_note": str}."""
    warmups, entries = layout(exercises, _placement)
    result = []
    if warmups:
        result.append({"warmup": True, "items": warmups, "labels": [], "section": "", "section_note": ""})
    for e in entries:
        if not e["first"]:
            result[-1]["items"].append(e["item"])
            result[-1]["labels"].append(e["label"])
            continue
        result.append(
            {
                "warmup": False,
                "items": [e["item"]],
                "labels": [e["label"]] if e["label"] else [],
                "section": e["section"],
                "section_note": e["section_note"],
            }
        )
    return result


def step_done(step):
    """A warm-up is done once every drill is ticked; an exercise screen once every
    planned set is (a set at least, for an exercise added without a plan)."""
    if step["warmup"]:
        return all(se.checked_at for se in step["items"])
    return all(sum(1 for s in se.sets.all() if s.done) >= max(planned_sets(se), 1) for se in step["items"])


def check_warmup(se, checked):
    se.checked_at = timezone.now() if checked else None
    se.save(update_fields=["checked_at"])
    return se


@transaction.atomic
def start(athlete, program_session):
    """The log for a planned session, created on first start with a snapshot of every
    prescription. Starting again (or twice at once) returns the same log."""
    existing = SessionLog.objects.filter(program_session=program_session).first()
    if existing:
        return existing
    day = program_session.day
    prescriptions = list(
        program_session.prescriptions.select_related("exercise__percent_of").prefetch_related("set_overrides")
    )
    try:
        with transaction.atomic():
            log = SessionLog.objects.create(
                athlete=athlete,
                program_session=program_session,
                date=day.date,
                name=program_session.name
                or session_name(rx.exercise.name for rx in prescriptions if not rx.warmup),
                week_type=day.week.week_type,
                # Filling in a missed day afterwards skips the "how do you feel today" check-in.
                checkin_skipped=day.date < athlete.today(),
            )
    except IntegrityError:
        return SessionLog.objects.get(program_session=program_session)
    SessionExercise.objects.bulk_create(
        [
            SessionExercise(
                session_log=log,
                prescription=rx,
                exercise=rx.exercise,
                exercise_name=rx.exercise.name,
                order=i,
                prescribed=snapshot(rx, athlete),
                warmup=rx.warmup,
            )
            for i, rx in enumerate(prescriptions)
        ]
    )
    return log


def save_set(se, set_number, *, load_kg, reps, duration_seconds, rir, done):
    row, _ = SetLog.objects.update_or_create(
        session_exercise=se,
        set_number=set_number,
        defaults={
            "load_kg": load_kg,
            "reps": reps,
            "duration_seconds": duration_seconds,
            "rir": rir,
            "done": done,
        },
    )
    log = se.session_log
    if log.finished:
        prs.apply(log)  # an edit within the 24 hours can change what the session set
    return row


@transaction.atomic
def finish(log, rpe, comment):
    log.session_rpe = rpe
    log.comment = comment
    if log.finished_at is None:
        log.finished_at = timezone.now()
    log.save(update_fields=["session_rpe", "comment", "finished_at"])
    prs.apply(log)
    return log
