"""Undo for edits within one program week (docs/BUILD_PLAN.md, "Undo").

Before each board edit, `record()` stores a JSON snapshot of the week (type, focus
note, sessions, prescriptions with every dose field, tags and per-set overrides).
`undo()` restores the latest snapshot and deletes it. Restoring matches rows by id, so
moved and edited exercises come back as they were; a session an athlete has logged is
never removed. Adding, duplicating or deleting weeks and applying templates aren't
recorded: they have their own confirm or preview.
"""

from decimal import Decimal

from django.db import transaction

from apps.exercises.models import Exercise, Tag

from .models import EditHistory, PrescribedSet, Prescription, ProgramSession, WeekType
from .prescriptions import COPIED_FIELDS

UNDO_DEPTH = 50


def _dec(value):
    return None if value is None else str(value)


def snapshot(week):
    sessions = []
    for session in (
        ProgramSession.objects.filter(day__week=week)
        .select_related("day")
        .prefetch_related("prescriptions__set_overrides", "prescriptions__tag_slot_tags")
    ):
        rxs = []
        for rx in session.prescriptions.all():
            fields = {f: getattr(rx, f) for f in COPIED_FIELDS}
            fields["load_value"] = _dec(fields["load_value"])
            rxs.append(
                {
                    "id": rx.pk,
                    "order": rx.order,
                    "exercise": rx.exercise_id,
                    "fields": fields,
                    "tags": [t.pk for t in rx.tag_slot_tags.all()],
                    "overrides": [
                        {
                            "set_number": s.set_number,
                            "rep_scheme": s.rep_scheme,
                            "reps": s.reps,
                            "load_value": _dec(s.load_value),
                        }
                        for s in rx.set_overrides.all()
                    ],
                }
            )
        sessions.append(
            {
                "id": session.pk,
                "date": session.day.date.isoformat(),
                "order": session.order,
                "name": session.name,
                "prescriptions": rxs,
            }
        )
    return {"week_type": week.week_type_id, "focus_note": week.focus_note, "sessions": sessions}


def record(week, user, label):
    EditHistory.objects.create(program_week=week, coach=user, label=label[:120], snapshot=snapshot(week))
    stale = EditHistory.objects.filter(program_week=week).values_list("pk", flat=True)[UNDO_DEPTH:]
    EditHistory.objects.filter(pk__in=list(stale)).delete()


def latest(week):
    return EditHistory.objects.filter(program_week=week).first()


@transaction.atomic
def undo(week):
    """Restore the latest snapshot; returns its label (None if there's nothing to undo)."""
    entry = latest(week)
    if entry is None:
        return None
    restore(week, entry.snapshot)
    label = entry.label
    entry.delete()
    return label


def restore(week, snap):
    week_type = WeekType.objects.filter(pk=snap["week_type"], gym=week.program.athlete.gym).first()
    if week_type:
        week.week_type = week_type
    week.focus_note = snap["focus_note"]
    week.save(update_fields=["week_type", "focus_note"])

    days = {d.date.isoformat(): d for d in week.days.all()}
    gym = week.program.athlete.gym
    restored_sessions, restored_rx = set(), set()
    # Put sessions and exercises back first, then delete what the snapshot didn't have:
    # deleting a session first would cascade to exercises that are about to move back.
    for s in snap["sessions"]:
        day = days.get(s["date"])
        if day is None:
            continue
        session = ProgramSession.objects.filter(pk=s["id"], day__week=week).first() or ProgramSession(day=day)
        session.day, session.order, session.name = day, s["order"], s["name"]
        session.save()
        restored_sessions.add(session.pk)
        for r in s["prescriptions"]:
            exercise = Exercise.objects.filter(pk=r["exercise"], gym=gym).first()
            if exercise is None:
                continue  # deleted from the library since
            rx = Prescription.objects.filter(pk=r["id"], session__day__week=week).first() or Prescription()
            rx.session, rx.order, rx.exercise = session, r["order"], exercise
            for field, value in r["fields"].items():
                setattr(rx, field, Decimal(value) if field == "load_value" and value is not None else value)
            rx.save()
            restored_rx.add(rx.pk)
            rx.tag_slot_tags.set(Tag.objects.filter(gym=gym, pk__in=r["tags"]))
            rx.set_overrides.all().delete()
            PrescribedSet.objects.bulk_create(
                [
                    PrescribedSet(
                        prescription=rx,
                        set_number=o["set_number"],
                        rep_scheme=o["rep_scheme"],
                        reps=o["reps"],
                        load_value=Decimal(o["load_value"]) if o["load_value"] is not None else None,
                    )
                    for o in r["overrides"]
                ]
            )
    logged = set(
        ProgramSession.objects.filter(day__week=week, logs__isnull=False).values_list("pk", flat=True)
    )
    # Sessions logged since the snapshot are never removed, nor their exercises.
    Prescription.objects.filter(session__day__week=week).exclude(pk__in=restored_rx).exclude(
        session_id__in=logged - restored_sessions
    ).delete()
    ProgramSession.objects.filter(day__week=week).exclude(pk__in=restored_sessions | logged).delete()
