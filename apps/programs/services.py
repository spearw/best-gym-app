"""Everything that changes an athlete's program. Views stay thin and call these.

Weeks are back-to-back from the program's start date, so inserting or deleting a
week shifts every later week (and its days) by seven days."""

import datetime

from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import PrescribedSet, Prescription, Program, ProgramDay, ProgramSession, ProgramWeek
from .prescriptions import default_dose, keep_warmups_first

WEEK = datetime.timedelta(days=7)


class HasLoggedSessions(Exception):
    """Logged sessions are history: their days can't be moved or deleted."""


def _has_logs(program, from_order):
    return ProgramSession.objects.filter(
        day__week__program=program, day__week__order__gte=from_order, logs__isnull=False
    ).exists()


def _empty_and_unused(session):
    """An unnamed session with no exercises and no log is just a rest day again."""
    return not session.name and not session.prescriptions.exists() and not session.logs.exists()


def locked_day_ids(week):
    """Days that clearing a week must leave alone: those with a completed session."""
    return set(
        ProgramDay.objects.filter(week=week, sessions__logs__finished_at__isnull=False)
        .values_list("pk", flat=True)
        .distinct()
    )


# ---------------------------------------------------------------- programs and weeks


def _create_week(program, order, week_type):
    start = program.start_date + WEEK * order
    week = ProgramWeek.objects.create(program=program, order=order, week_type=week_type, start_date=start)
    ProgramDay.objects.bulk_create(
        [ProgramDay(week=week, date=start + datetime.timedelta(days=i)) for i in range(7)]
    )
    return week


@transaction.atomic
def start_program(athlete, name, first_day, weeks, week_type, by):
    """Start a new program; the athlete's current one ends and is kept for history.
    `first_day` is snapped back to the gym's week-start day."""
    start = athlete.gym.week_start_for(first_day)
    athlete.programs.active().update(active=False, ended_at=timezone.now())
    program = Program.objects.create(athlete=athlete, name=name, start_date=start, created_by=by)
    for order in range(weeks):
        _create_week(program, order, week_type)
    return program


def _shift_weeks(program, from_order, by_weeks):
    """Move every week with order >= from_order (and its days) by `by_weeks`."""
    later = ProgramWeek.objects.filter(program=program, order__gte=from_order)
    delta = WEEK * by_weeks
    ProgramDay.objects.filter(week__in=later).update(date=F("date") + delta)
    later.update(order=F("order") + by_weeks, start_date=F("start_date") + delta)


@transaction.atomic
def add_week(program, week_type):
    next_order = (program.weeks.aggregate(m=Max("order"))["m"] if program.weeks.exists() else -1) + 1
    return _create_week(program, next_order, week_type)


@transaction.atomic
def duplicate_week(week):
    """Insert a copy right after `week`; later weeks shift a week later. The copy is
    unpublished, so the coach can review it before the athlete sees it."""
    if _has_logs(week.program, week.order + 1):
        raise HasLoggedSessions("Later weeks have logged sessions, so they can't move back a week.")
    _shift_weeks(week.program, week.order + 1, 1)
    copy = _create_week(week.program, week.order + 1, week.week_type)
    copy.focus_note = week.focus_note
    copy.save(update_fields=["focus_note"])
    new_days = {d.date - copy.start_date: d for d in copy.days.all()}
    for day in week.days.prefetch_related(
        "sessions__prescriptions__set_overrides", "sessions__prescriptions__tag_slot_tags"
    ):
        target = new_days[day.date - week.start_date]
        for session in day.sessions.all():
            _copy_session(session, target)
    return copy


def _copy_session(session, target_day, order=None):
    new = ProgramSession.objects.create(
        day=target_day, order=session.order if order is None else order, name=session.name
    )
    for rx in session.prescriptions.all():
        _copy_prescription(rx, new)
    return new


def _copy_prescription(rx, session):
    tags = list(rx.tag_slot_tags.all())
    overrides = list(rx.set_overrides.all())
    rx.pk = None
    rx.id = None
    rx._state.adding = True
    # Drop the original's prefetched relations, or .set() below compares against them and adds nothing.
    rx._prefetched_objects_cache = {}
    rx.session = session
    rx.save()
    rx.tag_slot_tags.set(tags)
    PrescribedSet.objects.bulk_create(
        [
            PrescribedSet(
                prescription=rx,
                set_number=s.set_number,
                rep_scheme=s.rep_scheme,
                reps=s.reps,
                load_value=s.load_value,
            )
            for s in overrides
        ]
    )
    return rx


@transaction.atomic
def delete_week(week):
    """Delete a week; every later week moves a week earlier so there's no gap."""
    program, order = week.program, week.order
    if _has_logs(program, order):
        raise HasLoggedSessions(
            "This week or a later one has logged sessions, so it can't be deleted or moved."
        )
    week.delete()
    _shift_weeks(program, order + 1, -1)


@transaction.atomic
def clear_week(week):
    """Remove every session from the week, except days with a completed session."""
    locked = locked_day_ids(week)
    ProgramSession.objects.filter(day__week=week).exclude(day_id__in=locked).delete()
    return len(locked)


def set_published(week, published):
    week.published = published
    week.published_at = timezone.now() if published else None
    week.save(update_fields=["published", "published_at"])


# ---------------------------------------------------------------- sessions and prescriptions


def session_for(day, session_id=None):
    """The session to add to: the given one, else the day's first (created if needed)."""
    if session_id:
        return day.sessions.get(pk=session_id)
    return day.sessions.first() or ProgramSession.objects.create(day=day, order=0)


def add_session(day, name=""):
    next_order = (day.sessions.aggregate(m=Max("order"))["m"] or 0) + 1 if day.sessions.exists() else 0
    return ProgramSession.objects.create(day=day, order=next_order, name=name)


@transaction.atomic
def add_prescription(day, exercise, athlete, session_id=None, index=None):
    """Add `exercise` to the day (its first session unless one is given), at the end or,
    when dragged in from the library, at position `index`."""
    session = session_for(day, session_id)
    next_order = (session.prescriptions.aggregate(m=Max("order"))["m"] or 0) + 1
    rx = Prescription.objects.create(
        session=session, order=next_order, exercise=exercise, **default_dose(exercise, athlete)
    )
    if index is not None:
        move_prescription(rx, session, index)
    else:
        keep_warmups_first(session)
    return rx


@transaction.atomic
def remove_prescription(rx):
    session = rx.session
    rx.delete()
    if _empty_and_unused(session):
        session.delete()


@transaction.atomic
def move_prescription(rx, target_session, index):
    """Put `rx` at position `index` in `target_session` (possibly another day)."""
    old_session = rx.session
    siblings = list(target_session.prescriptions.exclude(pk=rx.pk))
    index = max(0, min(index, len(siblings)))
    siblings.insert(index, rx)
    rx.session = target_session
    rx.save(update_fields=["session"])
    for order, item in enumerate(siblings):
        if item.order != order:
            Prescription.objects.filter(pk=item.pk).update(order=order)
    keep_warmups_first(target_session)
    if old_session.pk != target_session.pk:
        if _empty_and_unused(old_session):
            old_session.delete()
        else:
            _renumber(old_session)


def _renumber(session):
    for order, pk in enumerate(session.prescriptions.values_list("pk", flat=True)):
        Prescription.objects.filter(pk=pk).exclude(order=order).update(order=order)


def swap_exercise(rx, exercise):
    """Change the exercise, keeping the dose (sets, reps, load, notes, custom fields)."""
    rx.exercise = exercise
    rx.save(update_fields=["exercise"])
    return rx
