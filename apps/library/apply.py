"""Applying a template (or saved week) to an athlete: plan, preview, confirm.

`plan()` is a dry run used by both the preview and the confirm, so what the coach
reviews is exactly what gets written. The template's sessions run in order across
the chosen training days; a new calendar week starts when the days run out (the
mockup's planWeeks). Each new week takes the type and focus note of the template
week its first session came from.

Tag slots resolve per athlete: in "recent" mode to the exercise with all the slot's
tags that the athlete did most recently, else the slot's default.

Where the weeks go (`placements()`):
- "append": after the program's last week;
- "at:<week id>": from a future week on; empty weeks from there are replaced and weeks
  with work move after the new ones;
- "new:this" / "new:next": a new program (the current one ends and is kept) starting
  this week or next. With no program, these are the only choices.
New weeks arrive unpublished unless the coach ticks "publish now".
"""

import datetime
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import F

from apps.exercises.models import Exercise
from apps.programs import services as program_services
from apps.programs.models import Prescription, ProgramDay, ProgramSession, ProgramWeek

from . import services
from .models import TemplateApplication, TemplateKind

DEFAULT_DAYS = {1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5]}
WEEK = datetime.timedelta(days=7)
RECENT, DEFAULTS = "recent", "default"


class CannotApply(Exception):
    pass


@dataclass
class PlannedSession:
    source: object  # TemplateSession
    exercises: list  # [(slot, resolved exercise)]


@dataclass
class PlannedWeek:
    week_type: object
    focus_note: str
    days: dict = field(default_factory=dict)  # day offset (0-6 from the week start) -> PlannedSession

    @property
    def session_count(self):
        return len(self.days)


def default_days(template):
    return DEFAULT_DAYS.get(template.sessions_per_week, [0, 2, 4])


def _recent_by_exercise(athlete):
    from apps.workouts.history import exercise_history

    return {ex_id: entries[0].date for ex_id, entries in exercise_history(athlete, limit=1).items()}


def resolve(slot, athlete_recent, mode, tag_pool):
    """The exercise a slot becomes for this athlete."""
    if not slot.is_tag or mode != RECENT:
        return slot.exercise
    tag_ids = {t.pk for t in slot.tags.all()}
    candidates = [e for e in tag_pool if tag_ids <= e.tag_ids and e.pk in athlete_recent]
    if not candidates:
        return slot.exercise
    return max(candidates, key=lambda e: (athlete_recent[e.pk], -e.pk))


def plan(template, athlete, days, mode):
    """PlannedWeeks for applying `template` on the given day offsets."""
    days = sorted(set(days))
    if not days:
        return []
    recent = _recent_by_exercise(athlete) if mode == RECENT else {}
    pool = list(Exercise.objects.filter(gym=template.gym, archived=False).prefetch_related("tags"))
    for e in pool:
        e.tag_ids = {t.pk for t in e.tags.all()}
    weeks, current, used = [], None, 0
    for template_week in template.weeks.select_related("week_type").prefetch_related(
        "sessions__slots__exercise", "sessions__slots__tags", "sessions__slots__set_overrides"
    ):
        for session in template_week.sessions.all():
            if current is None or used >= len(days):
                current = PlannedWeek(template_week.week_type, template_week.focus_note)
                weeks.append(current)
                used = 0
            exercises = [(slot, resolve(slot, recent, mode, pool)) for slot in session.slots.all()]
            current.days[days[used]] = PlannedSession(session, exercises)
            used += 1
    return weeks


# ---------------------------------------------------------------- where the weeks go


@dataclass
class Placement:
    value: str
    label: str
    program: object = None  # None: a new program
    start_order: int = 0
    start_date: datetime.date = None
    replaced: list = field(default_factory=list)  # empty weeks that are replaced
    moved: list = field(default_factory=list)  # weeks with work that move after the new ones


def _has_work(week):
    return ProgramSession.objects.filter(day__week=week).exists()


def placements(athlete):
    today = athlete.today()
    gym = athlete.gym
    this_week = gym.week_start_for(today)
    options = []
    program = athlete.programs.active().first()
    if program:
        weeks = list(program.weeks.select_related("week_type"))
        if weeks and weeks[-1].end_date >= this_week:
            last = weeks[-1]
            options.append(
                Placement(
                    "append",
                    f"After {last.label} (append)",
                    program,
                    last.order + 1,
                    last.start_date + WEEK,
                )
            )
        for i, week in enumerate(weeks):
            if week.start_date <= today:
                continue
            later = weeks[i:]
            work = [w for w in later if _has_work(w)]
            empty = [w for w in later if w not in work]
            label = (
                f"Insert before {week.label} (it moves later)"
                if _has_work(week)
                else f"Start at {week.label} (empty — replaced)"
            )
            options.append(
                Placement(f"at:{week.pk}", label, program, week.order, week.start_date, empty, work)
            )
    name = "Start as a new program" if program else "New program"
    ends = " (ends the current one)" if program else ""
    options.append(Placement("new:this", f"{name} this week{ends}", None, 0, this_week))
    options.append(Placement("new:next", f"{name} next week{ends}", None, 0, this_week + WEEK))
    return options


def placement_for(athlete, value):
    options = placements(athlete)
    return next((p for p in options if p.value == value), options[0])


# ---------------------------------------------------------------- confirm


def _write_week(program, order, start_date, planned, publish):
    week = ProgramWeek.objects.create(
        program=program,
        order=order,
        week_type=planned.week_type,
        start_date=start_date,
        focus_note=planned.focus_note,
    )
    days = ProgramDay.objects.bulk_create(
        [ProgramDay(week=week, date=start_date + datetime.timedelta(days=i)) for i in range(7)]
    )
    for offset, session_plan in planned.days.items():
        session = ProgramSession.objects.create(day=days[offset], order=0, name=session_plan.source.name)
        for i, (slot, exercise) in enumerate(session_plan.exercises):
            rx = services.copy_dose(slot, Prescription(session=session, order=i, exercise=exercise))
            if slot.is_tag:
                rx.tag_slot_tags.set(slot.tags.all())
    if publish:
        program_services.set_published(week, True)
    return week


@transaction.atomic
def confirm(athlete, template, days, mode, placement_value, publish, by):
    """Write the planned weeks and prescribe the template's habits (skipping ones the
    athlete already has); returns (program, first new week, habits added)."""
    planned = plan(template, athlete, days, mode)
    if not planned:
        raise CannotApply(
            "Pick at least one training day."
            if not days
            else f"“{template.display_name}” has no sessions yet."
        )
    placement = placement_for(athlete, placement_value)
    n = len(planned)
    if placement.program is None:
        program = program_services.start_program(
            athlete, template.display_name, placement.start_date, 0, planned[0].week_type, by=by
        )
        if template.kind == TemplateKind.PROGRAM:
            program.source_template = template
            program.save(update_fields=["source_template"])
        start_order = 0
    else:
        program = placement.program
        start_order = placement.start_order
        later = ProgramWeek.objects.filter(program=program, order__gte=start_order)
        if ProgramSession.objects.filter(day__week__in=later, logs__isnull=False).exists():
            raise CannotApply("Those weeks have logged sessions, so they can't move.")
        for week in placement.replaced:
            week.delete()
        # Weeks with work move after the new ones, in order, back to back.
        for i, week in enumerate(
            ProgramWeek.objects.filter(program=program, order__gte=start_order).order_by("order")
        ):
            new_order = start_order + n + i
            delta = WEEK * (new_order - week.order)
            ProgramDay.objects.filter(week=week).update(date=F("date") + delta)
            ProgramWeek.objects.filter(pk=week.pk).update(order=new_order, start_date=F("start_date") + delta)
    first = None
    for i, planned_week in enumerate(planned):
        order = start_order + i
        week = _write_week(program, order, program.start_date + WEEK * order, planned_week, publish)
        first = first or week
    TemplateApplication.objects.create(template=template, athlete=athlete, applied_by=by, weeks=n)
    from apps.programs import habits

    added = sum(
        1
        for h in template.habits.all()
        if habits.prescribe(athlete, h.name, h.emoji, h.cadence, h.note, source_template=template)
    )
    return program, first, added
