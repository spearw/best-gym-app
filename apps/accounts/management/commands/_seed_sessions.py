"""The mockup's training history (CLIENTS[].hist and .checkins in mockup/index.html)
as session logs, for seed_demo.

- Every planned session before today is logged as done at the prescribed dose, except
  where the mockup's story has a missed day (Marcus skipped yesterday).
- The per-exercise history becomes one unprogrammed session per day, with the
  mockup's top set. Days that already have a planned session keep only that one.
- Check-ins (readiness, "anything affecting today", RPE, comment) attach to the
  session on the same day; sessions without one have the check-in skipped.
- A max recorded on the day of a history PR is linked to that set.
"""

import datetime
import zoneinfo
from decimal import Decimal

from apps.accounts.models import MaxEntry
from apps.exercises.models import Measure
from apps.programs.models import ProgramDay
from apps.workouts import sessions
from apps.workouts.models import (
    CheckinAnswer,
    CheckinQuestion,
    IssueKind,
    IssueReport,
    QuestionType,
    SessionExercise,
    SessionLog,
    SetLog,
)

# email: {exercise key: [(days ago, kg, reps), ...]}
HISTORY = {
    "maya@ironridge.example": {
        "sn": [
            (2, 78, 1),
            (5, 75, 2),
            (9, 76, 1),
            (12, 82, 1),
            (16, 74, 2),
            (23, 72, 2),
            (33, 74, 3),
            (44, 70, 3),
            (55, 68, 3),
        ],
        "cj": [(3, 98, 1), (7, 95, 1), (10, 96, 1), (17, 92, 2), (26, 104, 1), (38, 94, 2), (50, 90, 3)],
        "bsq": [(4, 122, 3), (8, 118, 5), (15, 125, 2), (22, 115, 5), (36, 120, 4), (48, 112, 5)],
        "fsq": [(6, 105, 2), (13, 100, 3)],
        "snp": [(2, 90, 3), (9, 88, 3)],
        "pp": [(8, 62, 4), (19, 60, 5)],
        "rdl": [(11, 95, 6), (25, 90, 8)],
        "snb": [(5, 70, 2)],
        "pc": [(16, 85, 2)],
    },
    "jonas@ironridge.example": {
        "sn": [(1, 100, 1), (8, 102, 1), (15, 98, 2)],
        "cj": [(3, 125, 1), (10, 122, 1)],
        "bsq": [(2, 170, 3), (9, 165, 4), (16, 172, 2)],
        "fj": [(1, 110, 1), (12, 115, 2)],
    },
    "priya@ironridge.example": {"sn": [(1, 48, 3), (8, 50, 2)], "bsq": [(2, 80, 5), (9, 78, 5)]},
    "marcus@ironridge.example": {"sn": [(3, 82, 1), (12, 85, 1)], "bsq": [(5, 140, 3)]},
    "lena@ironridge.example": {"sn": [(2, 55, 2), (9, 60, 2)]},
    "theo@ironridge.example": {"sn": [(1, 105, 2), (6, 110, 2)], "tsn": [(1, 120, 3)]},
}

# email: [(days ago, readiness, affecting, details, session RPE, comment), ...]
CHECKINS = {
    "maya@ironridge.example": [
        (2, 7, "Nothing — all good", "", 8, "Jerks felt snappy."),
        (4, 5, "Legs are sore", "", 9, "Squats were a grind."),
        (6, 8, "Nothing — all good", "", 7, ""),
    ],
    "jonas@ironridge.example": [
        (1, 4, "Shoulder discomfort", "Right shoulder pinches at jerk lockout", 8, "Cut jerks early."),
    ],
    "priya@ironridge.example": [(1, 9, "Nothing — all good", "", 6, "Could've done more!")],
    "marcus@ironridge.example": [(3, 3, "Poor sleep", "", 9, "The cut is wearing on me.")],
    "lena@ironridge.example": [(2, 6, "Nothing — all good", "", 5, "")],
    "theo@ironridge.example": [(1, 7, "Nothing — all good", "", 6, "Tempo work is humbling.")],
}

# email: [(hours ago, from the athlete?, text, read?)] — the mockup's message threads.
MESSAGES = {
    "maya@ironridge.example": [
        (26, False, "Nice work Tuesday. Numbers looked crisp on video.", True),
        (25, True, "Thanks! Felt the best it has all block.", True),
        (2, True, "Coach — for Saturday, are we going 78 or 80 for the second snatch opener attempt?", False),
    ],
    "jonas@ironridge.example": [
        (24, True, "Logged the shoulder thing in the issue report — not terrible but worth flagging.", True),
    ],
    "marcus@ironridge.example": [
        (5, True, "What's the sauna protocol this week? Trying to be smart about the last 1.5kg.", False),
    ],
    "lena@ironridge.example": [(48, False, "Deload week — bar speed only, nothing heavy.", True)],
}

MISSED = {"marcus@ironridge.example"}  # planned sessions before today left unlogged
ISSUES = {"jonas@ironridge.example": (1, IssueKind.PAIN, "Shoulder pinch at jerk lockout")}
DEFAULT_RPE = 7


def _at(date, hour, minute, tz):
    return datetime.datetime.combine(date, datetime.time(hour, minute), tzinfo=zoneinfo.ZoneInfo(tz))


def _finish(log, tz):
    log.started_at = _at(log.date, 17, 30, tz)
    log.finished_at = _at(log.date, 18, 45, tz)
    log.session_rpe = log.session_rpe or DEFAULT_RPE
    log.save()


def _log_planned(athlete, today):
    """Log each planned session before today at the prescribed dose; returns {date: log}."""
    logs = {}
    days = ProgramDay.objects.filter(
        week__program__athlete=athlete, week__program__active=True, week__published=True, date__lt=today
    ).prefetch_related("sessions")
    for day in days:
        for program_session in day.sessions.all():
            log = sessions.start(athlete, program_session)
            for se in log.exercises.all():
                p = sessions.prescribed(se)
                for number in range(1, (len(p.overrides) or p.sets) + 1):
                    override = next((o for o in p.overrides if o.set_number == number), None)
                    load = (
                        override.load_value if override and override.load_value is not None else p.load_value
                    )
                    kg = sessions.target_kg(p, load)
                    SetLog.objects.create(
                        session_exercise=se,
                        set_number=number,
                        load_kg=(Decimal(kg * 2).quantize(Decimal("1")) / 2) if kg else None,
                        reps=(override.reps if override and override.reps else p.reps),
                        duration_seconds=p.duration_seconds,
                        done=True,
                    )
            logs[day.date] = log
    return logs


def _log_history(athlete, exercises, today, taken, week_type_on):
    """One unprogrammed session per history day not already covered by a planned one."""
    by_day = {}
    for key, entries in HISTORY.get(athlete.user.email, {}).items():
        for days_ago, kg, reps in entries:
            by_day.setdefault(days_ago, []).append((exercises[key], kg, reps))
    logs = {}
    for days_ago, items in sorted(by_day.items()):
        date = today - datetime.timedelta(days=days_ago)
        if date in taken:
            continue
        log = SessionLog.objects.create(
            athlete=athlete,
            date=date,
            name=sessions.session_name(ex.name for ex, _kg, _reps in items),
            week_type=week_type_on(date),
        )
        for order, (exercise, kg, reps) in enumerate(items):
            se = SessionExercise.objects.create(
                session_log=log, exercise=exercise, exercise_name=exercise.name, order=order
            )
            s = SetLog.objects.create(
                session_exercise=se,
                set_number=1,
                load_kg=Decimal(kg),
                reps=reps if exercise.measure == Measure.REPS else None,
                done=True,
            )
            # The mockup's PR days: link the max recorded that day to the set that made it.
            MaxEntry.objects.filter(
                athlete=athlete, exercise=exercise, date=date, kg=Decimal(kg), set_log__isnull=True
            ).update(set_log=s)
        logs[date] = log
    return logs


def _checkin(athlete, log, entry):
    _days, readiness, affecting, details, rpe, comment = entry
    questions = list(CheckinQuestion.objects.for_athlete(athlete).active())
    scale = next((q for q in questions if q.type == QuestionType.SCALE), None)
    choice = next((q for q in questions if q.type == QuestionType.CHOICE), None)
    for order, (question, value, other) in enumerate(
        [(scale, str(readiness), ""), (choice, affecting, details)]
    ):
        if question is None:
            continue
        CheckinAnswer.objects.create(
            session_log=log,
            question=question,
            order=order,
            question_text=question.text,
            type=question.type,
            value=value,
            other_text=other,
        )
    log.session_rpe, log.comment, log.checkin_skipped = rpe, comment, False


def _week_type_finder(weeks):
    """The week type of the program week containing a date (the first week's before it)."""

    def week_type_on(date):
        for w in weeks:
            if w.start_date <= date <= w.end_date:
                return w.week_type
        return weeks[0].week_type if weeks else None

    return week_type_on


def seed_sessions(athletes_by_email, exercises, today):
    for email, athlete in athletes_by_email.items():
        athlete.session_logs.all().delete()  # demo data only: rebuilt on every seed
        athlete.issues.all().delete()
        tz = athlete.user.timezone
        program = athlete.programs.active().first()
        weeks = list(program.weeks.select_related("week_type")) if program else []

        week_type_on = _week_type_finder(weeks)

        planned = {} if email in MISSED else _log_planned(athlete, today)
        logs = {**_log_history(athlete, exercises, today, planned, week_type_on), **planned}
        for log in logs.values():
            log.checkin_skipped = True
        for entry in CHECKINS.get(email, []):
            log = logs.get(today - datetime.timedelta(days=entry[0]))
            if log is not None:
                _checkin(athlete, log, entry)
        for log in logs.values():
            _finish(log, tz)
        if email in ISSUES:
            days_ago, kind, text = ISSUES[email]
            IssueReport.objects.create(
                athlete=athlete,
                session_log=logs.get(today - datetime.timedelta(days=days_ago)),
                kind=kind,
                text=text,
            )
        _seed_messages(athlete, MESSAGES.get(email, []))
        if email in ISSUES:
            from apps.dashboard import alerts

            for issue in athlete.issues.all():
                alerts.issue_reported(issue)


def _seed_messages(athlete, messages):
    from django.utils import timezone

    from apps.dashboard import alerts
    from apps.dashboard.models import Notification
    from apps.messaging.models import Message, Thread

    Thread.objects.filter(athlete=athlete).delete()
    Notification.objects.filter(athlete=athlete).delete()
    thread = Thread.for_athlete(athlete)
    now = timezone.now()
    for hours, from_athlete, text, read in messages:
        sent = now - datetime.timedelta(hours=hours)
        sender = athlete.user if from_athlete else athlete.coach.user
        message = Message.objects.create(thread=thread, sender=sender, body=text)
        Message.objects.filter(pk=message.pk).update(sent_at=sent, read_at=sent if read else None)
        if from_athlete and not read:
            alerts.message_sent(message)


# email: [(name, emoji, cadence, note, streak, template it came from)] — the mockup's habits.
HABITS = {
    "maya@ironridge.example": [
        ("Eat 2 pieces of fruit", "🍎", "daily", "", 11, None),
        ("In bed by 10:30pm", "😴", "daily", "Sleep is part of the program this block", 4, None),
        ("10-min ankle mobility", "🧘", "training", "Before every session", 7, "12-Week Competition Cycle"),
    ],
    "jonas@ironridge.example": [
        ("Shoulder rehab band work", "💪", "training", "Physio protocol, 2 rounds", 2, None),
    ],
}


def seed_habits(athletes_by_email, today):
    """Habits with enough ticks behind them to show the mockup's streaks."""
    from django.utils import timezone

    from apps.library.models import Template
    from apps.programs.habits import training_dates
    from apps.programs.models import Habit, HabitLog

    for email, athlete in athletes_by_email.items():
        athlete.habits.all().delete()  # demo data only: rebuilt on every seed
        for order, (name, emoji, cadence, note, streak, source) in enumerate(HABITS.get(email, [])):
            habit = Habit.objects.create(
                athlete=athlete,
                order=order,
                name=name,
                emoji=emoji,
                cadence=cadence,
                note=note,
                source_template=Template.objects.filter(gym=athlete.gym, name=source).first()
                if source
                else None,
            )
            Habit.objects.filter(pk=habit.pk).update(created_at=timezone.now() - datetime.timedelta(days=60))
            if cadence == "training":
                days = sorted(
                    (
                        d
                        for d in training_dates(athlete, today - datetime.timedelta(days=60), today)
                        if d < today
                    ),
                    reverse=True,
                )
            else:
                days = [today - datetime.timedelta(days=i) for i in range(1, 61)]
            # The streak, then a missed day, then a few scattered earlier ticks.
            done = days[:streak] + days[streak + 1 : streak + 6 : 2]
            HabitLog.objects.bulk_create([HabitLog(habit=habit, date=d) for d in done])
