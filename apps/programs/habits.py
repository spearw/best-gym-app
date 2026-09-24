"""Habits: what's due on a day, ticking, and streaks (docs/BUILD_PLAN.md, phase 7).

- Every day: due daily; the streak is days in a row done.
- Training days: due only on days with a session in a published week of the active
  program; the streak counts those days.
- 3× / 5× a week: due every day until done that many times in the (gym's) week, then
  "done for this week"; the streak is weeks in a row the target was hit.
For all of them, today only breaks a streak once it's over. Athletes can tick today and
yesterday (TICKABLE_DAYS).
"""

import datetime

from django.utils import timezone

from .models import Habit, HabitLog, ProgramDay

DAY = datetime.timedelta(days=1)
TICKABLE_DAYS = 2  # today and yesterday


def active(athlete):
    return athlete.habits.filter(archived_at__isnull=True)


def training_dates(athlete, start, end):
    return set(
        ProgramDay.objects.filter(
            week__program__athlete=athlete,
            week__program__active=True,
            week__published=True,
            sessions__isnull=False,
            date__gte=start,
            date__lte=end,
        ).values_list("date", flat=True)
    )


def _done_dates(habit, start, end):
    return set(habit.logs.filter(date__gte=start, date__lte=end).values_list("date", flat=True))


def week_count(habit, date):
    start = habit.athlete.gym.week_start_for(date)
    return len(_done_dates(habit, start, start + 6 * DAY))


def is_due(habit, date, training=None):
    if habit.cadence == Habit.Cadence.TRAINING:
        training = training if training is not None else training_dates(habit.athlete, date, date)
        return date in training
    return True


def streak(habit, today):
    """Days (or, for weekly targets, weeks) in a row, counted back from today."""
    athlete = habit.athlete
    if habit.weekly_target:
        gym = athlete.gym
        week = gym.week_start_for(today)
        count = 0
        if week_count(habit, today) >= habit.weekly_target:
            count += 1
        week -= 7 * DAY
        while week_count(habit, week) >= habit.weekly_target:
            count += 1
            week -= 7 * DAY
        return count
    lookback = today - 400 * DAY
    done = _done_dates(habit, lookback, today)
    if habit.cadence == Habit.Cadence.TRAINING:
        days = sorted(training_dates(athlete, lookback, today), reverse=True)
    else:
        # Every day back from today; the count stops at the first day not done.
        days = [today - i * DAY for i in range((today - lookback).days + 1)]
    count = 0
    for day in days:
        if day == today and day not in done:
            continue  # today isn't missed until it's over
        if day not in done:
            break
        count += 1
    return count


def last_seven(habit, today):
    """[(date, done)] for the last 7 days, oldest first (the coach's dots)."""
    done = _done_dates(habit, today - 6 * DAY, today)
    return [(today - i * DAY, today - i * DAY in done) for i in range(6, -1, -1)]


def for_day(athlete, date):
    """The athlete's habits for a day: those due, plus weekly ones already met ("done for
    this week"). Each item: habit, done (that day), streak, met_for_week."""
    habits = list(active(athlete))
    training = training_dates(athlete, date, date)
    items = []
    today = athlete.today()
    for h in habits:
        done = h.logs.filter(date=date).exists()
        target = h.weekly_target
        count = week_count(h, date) if target else None
        met = bool(target) and count >= target and not done
        if not is_due(h, date, training) and not done:
            continue
        items.append(
            {
                "habit": h,
                "done": done,
                "met_for_week": met,
                "week_count": count,
                "streak": streak(h, today),
            }
        )
    return items


class CannotTick(Exception):
    pass


def toggle(habit, date):
    today = habit.athlete.today()
    if not today - (TICKABLE_DAYS - 1) * DAY <= date <= today:
        raise CannotTick("Only today and yesterday can be ticked.")
    log = habit.logs.filter(date=date).first()
    if log:
        log.delete()
        return False
    HabitLog.objects.create(habit=habit, date=date)
    return True


def prescribe(athlete, name, emoji, cadence, note, source_template=None):
    """Add a habit unless the athlete already has an active one with that name."""
    if active(athlete).filter(name__iexact=name).exists():
        return None
    return Habit.objects.create(
        athlete=athlete,
        order=athlete.habits.count(),
        name=name,
        emoji=emoji,
        cadence=cadence,
        note=note,
        source_template=source_template,
    )


def archive(habit):
    habit.archived_at = timezone.now()
    habit.save(update_fields=["archived_at"])
