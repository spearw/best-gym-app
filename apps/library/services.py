"""Changes to templates, saved weeks and saved sessions. Views stay thin.

Copying is the heart of it: weeks, sessions and slots are copied (never shared)
between templates, the library and athletes' programs, so editing one never changes
another. `copy_dose` moves every PrescriptionBase field, the per-set overrides and
the tags between a Prescription and a TemplateSlot, in either direction.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import F, Max

from apps.programs.models import LoadBasis, WeekType
from apps.programs.prescriptions import COPIED_FIELDS, DEFAULTS, parse_rep_scheme

from .models import (
    SlotKind,
    Template,
    TemplateHabit,
    TemplateKind,
    TemplateSession,
    TemplateSlot,
    TemplateWeek,
)

STARTER_SESSIONS = {TemplateKind.PROGRAM: 3, TemplateKind.WEEK: 2, TemplateKind.SESSION: 1}


def session_letter(n):
    return f"Session {chr(65 + n)}" if n < 26 else f"Session {n + 1}"


def default_week_type(gym):
    return WeekType.objects.active().filter(gym=gym).first() or WeekType.objects.filter(gym=gym).first()


# ---------------------------------------------------------------- copying doses


def bump(value, basis, points):
    """A percentage load raised by `points` (e.g. +2.5); other loads are unchanged."""
    if not points or value is None or basis != LoadBasis.PERCENT:
        return value
    return max(Decimal("1"), Decimal(value) + Decimal(points))


def copy_dose(src, dst, points=None):
    """Copy every dose field (and the per-set overrides) from `src` onto `dst` and save.
    `points` bumps percentage loads. `dst` must have its parent and exercise set."""
    for field in COPIED_FIELDS:
        setattr(dst, field, getattr(src, field))
    dst.load_value = bump(dst.load_value, dst.load_basis, points)
    dst.pk = None
    dst.save()
    overrides = dst.set_overrides.model
    parent = dst.set_overrides.field.name
    overrides.objects.bulk_create(
        [
            overrides(
                **{parent: dst},
                set_number=s.set_number,
                rep_scheme=s.rep_scheme,
                reps=s.reps,
                load_value=bump(s.load_value, src.load_basis, points),
            )
            for s in src.set_overrides.all()
        ]
    )
    return dst


def _src_tags(src):
    return list(src.tags.all()) if isinstance(src, TemplateSlot) else list(src.tag_slot_tags.all())


def slot_from(src, session, order, points=None):
    """A TemplateSlot copied from a slot or a program prescription (tag slots stay tag slots)."""
    tags = _src_tags(src)
    kind = SlotKind.TAG if tags else SlotKind.EXERCISE
    slot = copy_dose(
        src, TemplateSlot(session=session, order=order, kind=kind, exercise=src.exercise), points
    )
    slot.tags.set(tags)
    return slot


def copy_session(src, week, order, name=None, points=None):
    """Copy a template session (or a program session) with all its exercises."""
    session = TemplateSession.objects.create(week=week, order=order, name=src.name if name is None else name)
    items = src.slots.all() if isinstance(src, TemplateSession) else src.prescriptions.all()
    for i, item in enumerate(items):
        slot_from(item, session, i, points)
    return session


def copy_week(src, template, order, points=None):
    week = TemplateWeek.objects.create(
        template=template, order=order, week_type=src.week_type, focus_note=src.focus_note
    )
    for i, session in enumerate(src.sessions.all()):
        copy_session(session, week, i, points=points)
    return week


def _renumber(queryset):
    for order, pk in enumerate(queryset.values_list("pk", flat=True)):
        queryset.model.objects.filter(pk=pk).exclude(order=order).update(order=order)


# ---------------------------------------------------------------- templates


@transaction.atomic
def new_template(gym, kind, by):
    """An empty template, week or session, laid out like the mockup's "+ New" buttons."""
    template = Template.objects.create(
        gym=gym, kind=kind, created_by=by, sessions_per_week=STARTER_SESSIONS[kind]
    )
    week = TemplateWeek.objects.create(template=template, order=0, week_type=default_week_type(gym))
    for i in range(STARTER_SESSIONS[kind]):
        TemplateSession.objects.create(
            week=week, order=i, name=session_letter(i) if kind != "session" else ""
        )
    return template


def single_week(template):
    """The only week of a saved week or saved session (created if somehow missing)."""
    week = template.weeks.first()
    return week or TemplateWeek.objects.create(template=template, week_type=default_week_type(template.gym))


@transaction.atomic
def add_week(template, points=None):
    """A new last week: a copy of the previous one (percentages bumped by `points`),
    or one empty session if the template has no weeks."""
    last = template.weeks.last()
    order = (template.weeks.aggregate(m=Max("order"))["m"] or 0) + 1 if last else 0
    if last is None:
        week = TemplateWeek.objects.create(
            template=template, order=0, week_type=default_week_type(template.gym)
        )
        TemplateSession.objects.create(week=week, order=0, name=session_letter(0))
        return week
    return copy_week(last, template, order, points)


@transaction.atomic
def add_saved_week(template, saved):
    order = (template.weeks.aggregate(m=Max("order"))["m"] or -1) + 1
    return copy_week(single_week(saved), template, order)


@transaction.atomic
def duplicate_week(week):
    template = week.template
    template.weeks.filter(order__gt=week.order).update(order=F("order") + 1)
    return copy_week(week, template, week.order + 1)


@transaction.atomic
def remove_week(week):
    template = week.template
    week.delete()
    _renumber(template.weeks.all())


@transaction.atomic
def add_session(week, name=None):
    n = week.sessions.count()
    return TemplateSession.objects.create(
        week=week, order=n, name=session_letter(n) if name is None else name
    )


@transaction.atomic
def add_saved_session(week, saved):
    source = single_week(saved).sessions.first()
    if source is None:
        return add_session(week, saved.display_name)
    return copy_session(source, week, week.sessions.count(), name=saved.display_name)


@transaction.atomic
def remove_session(session):
    week = session.week
    session.delete()
    _renumber(week.sessions.all())


def new_slot_dose(exercise):
    dose = dict(DEFAULTS[exercise.measure])
    dose["reps"], dose["duration_seconds"] = parse_rep_scheme(dose["rep_scheme"])
    return dose


@transaction.atomic
def add_slot(session, exercise, index=None, tags=None):
    """A fixed slot (or a tag slot when `tags` is given) at the end, or at `index`."""
    slot = TemplateSlot.objects.create(
        session=session,
        order=session.slots.count(),
        kind=SlotKind.TAG if tags else SlotKind.EXERCISE,
        exercise=exercise,
        **new_slot_dose(exercise),
    )
    if tags:
        slot.tags.set(tags)
    if index is not None:
        move_slot(slot, session, index)
    return slot


@transaction.atomic
def move_slot(slot, target, index):
    old = slot.session
    siblings = list(target.slots.exclude(pk=slot.pk))
    index = max(0, min(index, len(siblings)))
    siblings.insert(index, slot)
    slot.session = target
    slot.save(update_fields=["session"])
    for order, item in enumerate(siblings):
        if item.order != order:
            TemplateSlot.objects.filter(pk=item.pk).update(order=order)
    if old.pk != target.pk:
        _renumber(old.slots.all())


@transaction.atomic
def remove_slot(slot):
    session = slot.session
    slot.delete()
    _renumber(session.slots.all())


def add_habit(template, name, emoji, cadence, note):
    return TemplateHabit.objects.create(
        template=template, order=template.habits.count(), name=name, emoji=emoji, cadence=cadence, note=note
    )


# ---------------------------------------------------------------- saving boards into the library


def board_sessions(program_week):
    """(name, ProgramSession) for each session with work in a program week, in day order.
    An unnamed session is named after its weekday."""
    found = []
    for day in program_week.days.prefetch_related("sessions__prescriptions"):
        for session in day.sessions.all():
            if session.prescriptions.exists():
                found.append((session.name or day.date.strftime("%A"), session))
    return found


@transaction.atomic
def save_week(gym, by, program_week, name, description=""):
    sessions = board_sessions(program_week)
    template = Template.objects.create(
        gym=gym,
        kind=TemplateKind.WEEK,
        name=name,
        description=description,
        created_by=by,
        sessions_per_week=max(1, min(6, len(sessions))),
    )
    week = TemplateWeek.objects.create(
        template=template, order=0, week_type=program_week.week_type, focus_note=program_week.focus_note
    )
    for i, (session_name, session) in enumerate(sessions):
        copy_session(session, week, i, name=session_name)
    return template


@transaction.atomic
def save_session(gym, by, source, name, description=""):
    """Save a template session or a program session as a saved session."""
    template = Template.objects.create(
        gym=gym,
        kind=TemplateKind.SESSION,
        name=name,
        description=description,
        created_by=by,
        sessions_per_week=1,
    )
    week_type = source.week.week_type if isinstance(source, TemplateSession) else source.day.week.week_type
    week = TemplateWeek.objects.create(template=template, order=0, week_type=week_type)
    copy_session(source, week, 0, name="")
    return template


@transaction.atomic
def save_template_week(gym, by, template_week, name, description=""):
    template = Template.objects.create(
        gym=gym,
        kind=TemplateKind.WEEK,
        name=name,
        description=description,
        created_by=by,
        sessions_per_week=max(1, min(6, template_week.sessions.count())),
    )
    copy_week(template_week, template, 0)
    return template


@transaction.atomic
def save_program(gym, by, program, name, description=""):
    """An athlete's program as a template: every week with work, its sessions in day order."""
    template = Template.objects.create(
        gym=gym, kind=TemplateKind.PROGRAM, name=name, description=description, created_by=by
    )
    most = 1
    order = 0
    for program_week in program.weeks.select_related("week_type"):
        sessions = board_sessions(program_week)
        if not sessions:
            continue
        week = TemplateWeek.objects.create(
            template=template,
            order=order,
            week_type=program_week.week_type,
            focus_note=program_week.focus_note,
        )
        for i, (session_name, session) in enumerate(sessions):
            copy_session(session, week, i, name=session_name)
        most = max(most, len(sessions))
        order += 1
    template.sessions_per_week = min(6, most)
    template.save(update_fields=["sessions_per_week"])
    return template
