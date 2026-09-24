"""A real client's program style for seed_demo (phase 9): "Meso 1", a 4-day
powerbuilding block programmed by RIR, with warm-up drills linked to YouTube demos,
Strength / Hypertrophy sections, supersets and a program note. It comes from the
client's spreadsheet (mockup/Export For Sir Steven.xlsx). The athlete is made up: the
name is invented and the notes are paraphrased, so nothing identifies the real person.

Riley trains in pounds. The block started two weeks before this one: weeks 1-2 are
logged, week 3 is logged up to yesterday, week 4 is ahead. The Day 4 session of week 1
was never logged, as in the sheet.
"""

import datetime
import zoneinfo
from decimal import Decimal

from django.utils import timezone

from apps.accounts import units
from apps.accounts.models import Athlete, BodyweightEntry, MeasurementSource
from apps.exercises.models import Category, Exercise, Measure
from apps.library import apply
from apps.library.models import Template, TemplateKind, TemplateSession, TemplateWeek
from apps.library.services import add_slot, copy_week
from apps.programs import services as program_services
from apps.programs.models import LoadBasis, WeekType
from apps.programs.prescriptions import parse_rep_scheme
from apps.workouts import sessions
from apps.workouts.models import (
    CheckinAnswer,
    CheckinQuestion,
    IssueKind,
    IssueReport,
    QuestionType,
    SetLog,
)

EMAIL = "riley@ironridge.example"
NAME = "Riley Brooks"
TEMPLATE_NAME = "Meso 1 — Powerbuilding"
PROGRAM_NOTE = (
    "Powerbuilding: strength and hypertrophy, with some cardio.\n"
    "Goal: get strong, build muscle and stay healthy.\n"
    "Rest as needed on all lifts.\n"
    "Nutrition: we can go into more detail whenever you want."
)
YT = "https://www.youtube.com/watch?v="

# name: (category, measure, YouTube id or "", warm-up drill?)
EXERCISES = {
    "Rower": ("Conditioning", Measure.TIME, "", False),
    "Incline Treadmill Walk": ("Conditioning", Measure.TIME, "", False),
    "Posterior Capsule Release w/ Rotation": ("Mobility", Measure.REPS, "YRAHfnBXEmw", True),
    "Posterior Capsule Release": ("Mobility", Measure.REPS, "jTXy0j40SJQ", True),
    "Bench Hip Adduction": ("Mobility", Measure.REPS, "6Ob8Wr0hHtc", True),
    "Deep Squat Lat Hang + Hip Shifts": ("Mobility", Measure.REPS, "ljOLhAd8e7Y", True),
    "Rack Supported Hinge Split Squat": ("Mobility", Measure.REPS, "UijuYPYyjuU4", True),
    "Heels Elevated Goblet Squat Hold": ("Mobility", Measure.REPS, "y2kDnv65McI", True),
    "Half Kneeling Windmill": ("Mobility", Measure.REPS, "_cACiET0uUM", True),
    "Back Squat": ("Squat", Measure.REPS, "", False),
    "Pull-up": ("Accessory", Measure.REPS, "", False),
    "DB Bench Press": ("Press", Measure.REPS, "", False),
    "1-Arm DB Row": ("Accessory", Measure.REPS, "", False),
    "Reverse Lunge": ("Squat", Measure.REPS, "", False),
    "Standing Calf Raise": ("Accessory", Measure.REPS, "", False),
    "Incline Barbell Bench Press": ("Press", Measure.REPS, "", False),
    "Romanian Deadlift": ("Pull", Measure.REPS, "", False),
    "Bulgarian Split Squat": ("Squat", Measure.REPS, "", False),
    "Lateral Raise": ("Accessory", Measure.REPS, "", False),
    "Hammer Curl": ("Accessory", Measure.REPS, "", False),
    "Tricep Rollback": ("Accessory", Measure.REPS, "w_mrVg8JH_g", False),
    "Deadlift": ("Pull", Measure.REPS, "", False),
    "Strict Press": ("Press", Measure.REPS, "", False),
    "Barbell Row": ("Accessory", Measure.REPS, "jqr1i_249As", False),
    "Copenhagen Plank": ("Accessory", Measure.TIME, "aDsaGBnvDQo", False),
    "Hanging Leg Raise": ("Accessory", Measure.REPS, "", False),
}


def wu(name, dose="", note=""):
    return {"name": name, "warmup": True, "rep_scheme": dose, "note": note}


def lift(name, sets, reps, rir="", rpe_sets=(), note="", section="", section_note="", superset=False):
    low, _, high = rir.partition("-")
    return {
        "name": name,
        "sets": sets,
        "rep_scheme": reps,
        "rir": int(low) if low else None,
        "rir_max": int(high) if high else None,
        "rpe_sets": rpe_sets,
        "note": note,
        "section": section,
        "section_note": section_note,
        "superset": superset,
    }


TOP_SET = (8, 9, 7)  # the sheet's "@8RPE, @9RPE, @7RPE" on each day's main lift
SESSIONS = [
    (
        "Day 1 — Squat",
        [
            wu("Rower", "5 min", "Cardio warm-up"),
            wu("Posterior Capsule Release w/ Rotation", "x 5 breaths"),
            wu("Bench Hip Adduction", "x 8"),
            wu("Deep Squat Lat Hang + Hip Shifts", "x 5 breaths + 5 shifts"),
            wu("Rack Supported Hinge Split Squat", "x 10, 3-0-3-0 tempo", "No weight"),
            wu("Heels Elevated Goblet Squat Hold", "x 3"),
            lift(
                "Back Squat",
                3,
                "5",
                rpe_sets=TOP_SET,
                note="Add pause reps to your warm-up sets",
                section="Strength",
            ),
            lift(
                "Pull-up",
                3,
                "6-8",
                "1-2",
                note="Can't do bodyweight yet? Use a band",
                section="Hypertrophy",
                section_note="Superset non-competing exercises when available",
            ),
            lift("DB Bench Press", 3, "10-12", "1-2"),
            lift("1-Arm DB Row", 3, "10-12", "2-3"),
            lift("Reverse Lunge", 3, "10/leg", "1-2", note="Dumbbells or barbell"),
            lift("Standing Calf Raise", 3, "15-20", "1-2", note="Hold the sides of the rack for balance"),
        ],
    ),
    (
        "Day 2 — Bench",
        [
            wu("Rower", "1000 m @ RPE 8", "Cardio warm-up"),
            wu("Posterior Capsule Release", "x 5 breaths"),
            wu("Deep Squat Lat Hang + Hip Shifts", "x 5 breaths + 5 shifts"),
            wu("Half Kneeling Windmill", "x 3", "Exhale, then inhale at the bottom of each rep"),
            lift("Incline Barbell Bench Press", 3, "5", rpe_sets=TOP_SET, section="Strength"),
            lift(
                "Romanian Deadlift",
                3,
                "10-12",
                "1-2",
                section="Hypertrophy",
                section_note="Superset non-competing exercises when available",
            ),
            lift("Bulgarian Split Squat", 3, "10-12", "1-2", note="Use a bench if there's no pad"),
            lift("Lateral Raise", 3, "10-12", "1-2", superset=True),
            lift("Hammer Curl", 3, "15-20", "1-2"),
            lift("Tricep Rollback", 2, "15-20", "1-2", superset=True),
        ],
    ),
    (
        "Day 3 — Cardio",
        [lift("Incline Treadmill Walk", 1, "20-30 min", section="Cardiac development (intervals)")],
    ),
    (
        "Day 4 — Deadlift",
        [
            wu("Incline Treadmill Walk", "5-10 min", "Cardio warm-up"),
            wu("Posterior Capsule Release w/ Rotation", "x 5 breaths"),
            wu("Bench Hip Adduction", "x 8"),
            wu("Deep Squat Lat Hang + Hip Shifts", "x 5 breaths + 5 shifts"),
            wu("Rack Supported Hinge Split Squat", "x 10, 3-0-3-0 tempo", "No weight"),
            wu("Heels Elevated Goblet Squat Hold", "x 3"),
            lift("Deadlift", 3, "5", rpe_sets=TOP_SET, section="Strength"),
            lift("Strict Press", 3, "5", "1-2"),
            lift("Barbell Row", 3, "10-12", "2-3", section="Hypertrophy"),
            lift("Reverse Lunge", 3, "10-12", "1-2"),
            lift("Copenhagen Plank", 3, "10 s", note="We'll build these up"),
            lift("Hanging Leg Raise", 2, "10-12", "1-2", note="Bent knees are fine for now"),
        ],
    ),
]

# What was logged, from the sheet: {session: {exercise: [week 1, week 2, week 3]}}, each
# week (load in lb or None, [reps per set], [RIR per set] or None). None = not logged.
BW = None
LOGGED = {
    "Day 1 — Squat": {
        "Back Squat": [(255, [5, 5, 5], [3, 2, 3]), (260, [5, 5, 5], [2, 2, 2]), (260, [5, 5, 5], [2, 2, 2])],
        "Pull-up": [(BW, [6, 6, 6], None), (BW, [6, 6, 6], None), (BW, [6, 6, 6], None)],
        "DB Bench Press": [(45, [12, 12, 12], None), (45, [12, 12, 12], None), (45, [12, 12, 12], [5, 5, 5])],
        "1-Arm DB Row": [(45, [12, 12, 12], None)] * 3,
        "Reverse Lunge": [(70, [10, 10, 10], None)] * 3,
        "Standing Calf Raise": [(105, [20, 20, 20], [5, 5, 5]), (125, [15, 15], None), (125, [20], None)],
    },
    "Day 2 — Bench": {
        "Incline Barbell Bench Press": [
            (120, [5, 5, 5], [4, 3, 2]),
            (135, [5, 5, 5], [1, 2, 1]),
            (135, [5, 5, 5], [2, 2, 2]),
        ],
        "Romanian Deadlift": [
            (125, [12, 12, 12], None),
            (135, [12, 12, 12], None),
            (135, [12, 12, 12], [3, 4, 4]),
        ],
        "Bulgarian Split Squat": [(50, [12, 10, 10], None)] * 3,
        "Lateral Raise": [(10, [10, 10, 10], None), (10, [12, 12, 12], None), (10, [12, 12, 12], None)],
        "Hammer Curl": [(15, [15, 15, 15], None)] * 3,
        "Tricep Rollback": [(15, [15, 15], None)] * 3,
    },
    "Day 3 — Cardio": {"Incline Treadmill Walk": [("25 min", [], None)] * 3},
    "Day 4 — Deadlift": {
        "Deadlift": [None, (225, [5, 5, 5], [3, 3, 3]), (235, [5, 5, 5], [2, 2, 3])],
        "Strict Press": [None, (95, [5, 5, 5], None), (95, [5, 5, 5], None)],
        "Barbell Row": [None, (95, [12, 12, 12], None), (95, [12, 12, 12], None)],
        "Reverse Lunge": [None, (70, [12, 12], None), (70, [12, 12, 12], None)],
        "Copenhagen Plank": [None, ("10 s", [], None), ("10 s", [], None)],
        "Hanging Leg Raise": [None, (BW, [12, 12], None), (BW, [12, 12], None)],
    },
}

# {(session, week): (soreness, where, recovery, other notes, session RPE, comment)}; paraphrased.
CHECKINS = {
    ("Day 1 — Squat", 0): (
        1,
        "",
        10,
        "",
        7,
        "Squats felt good, 3-4 in the tank. No incline platform, fine without.",
    ),
    ("Day 1 — Squat", 1): (4, "legs", 7, "", 8, "The lunges wrecked me."),
    ("Day 1 — Squat", 2): (6, "hips", 6, "", 8, "Cardio's getting better. Ran short on time for calves."),
    ("Day 2 — Bench", 0): (
        8,
        "thighs",
        7,
        "Thighs are really sore, everything else is fine",
        7,
        "Still finding the right incline weight.",
    ),
    ("Day 2 — Bench", 1): (3, "", 8, "", 7, ""),
    ("Day 2 — Bench", 2): (3, "", 7, "Slept funny, stiff neck", 7, "RDLs were 3-4 RIR — going up next week."),
    ("Day 4 — Deadlift", 1): (
        4,
        "",
        7,
        "",
        8,
        "Deadlifts felt heavier than they should. Only got two sets of lunges in.",
    ),
}


def _exercises(gym):
    found = {}
    for name, (category, measure, yt, warmup) in EXERCISES.items():
        cat, _ = Category.objects.get_or_create(gym=gym, name=category, defaults={"order": 99})
        exercise = Exercise.objects.filter(gym=gym, name=name).first()
        if exercise is None:
            exercise = Exercise.objects.create(gym=gym, name=name, category=cat, measure=measure)
        exercise.archived = False
        exercise.warmup = warmup
        if yt:
            exercise.youtube_url = YT + yt
        exercise.save()
        found[name] = exercise
    return found


def _template(gym, coach_user, exercises):
    Template.objects.filter(gym=gym, name=TEMPLATE_NAME).delete()
    template = Template.objects.create(
        gym=gym,
        kind=TemplateKind.PROGRAM,
        name=TEMPLATE_NAME,
        description="4 days: squat, bench, cardio, deadlift. Strength by RPE, hypertrophy by RIR.",
        program_note=PROGRAM_NOTE,
        sessions_per_week=4,
        created_by=coach_user,
    )
    week_type = WeekType.objects.filter(gym=gym, archived=False).first()
    week = TemplateWeek.objects.create(template=template, order=0, week_type=week_type)
    for i, (session_name, items) in enumerate(SESSIONS):
        session = TemplateSession.objects.create(week=week, order=i, name=session_name)
        for item in items:
            slot = add_slot(session, exercises[item["name"]])
            reps, seconds = parse_rep_scheme(item.get("rep_scheme", ""))
            slot.rep_scheme, slot.reps, slot.duration_seconds = item.get("rep_scheme", ""), reps, seconds
            slot.note, slot.warmup = item.get("note", ""), item.get("warmup", False)
            if slot.warmup:
                slot.sets, slot.load_basis, slot.load_value = 1, LoadBasis.NONE, None
            else:
                slot.sets = item["sets"]
                slot.rir, slot.rir_max = item["rir"], item["rir_max"]
                slot.section, slot.section_note = item["section"], item["section_note"]
                slot.superset = item["superset"]
                if item["rpe_sets"]:
                    slot.load_basis = LoadBasis.RPE
                    slot.load_value = Decimal(item["rpe_sets"][0])
            slot.save()
            for n, rpe in enumerate(item.get("rpe_sets", ()), start=1):
                slot.set_overrides.create(set_number=n, rep_scheme="", reps=reps, load_value=Decimal(rpe))
    for order in range(1, 4):
        copy_week(week, template, order)
    return template


def _athlete(coach, gym, today):
    from apps.accounts.models import User

    user, created = User.objects.update_or_create(
        email=EMAIL, defaults={"name": NAME, "timezone": gym.timezone}
    )
    if created:
        from django.conf import settings

        user.set_password(settings.DEMO_PASSWORD)
        user.save(update_fields=["password"])
    athlete, _ = Athlete.objects.update_or_create(
        user=user,
        defaults={
            "coach": coach,
            "gym": gym,
            "height_cm": Decimal("178"),
            "years_training": "1-3",
            "units": "lb",
            "archived_at": None,
        },
    )
    athlete.session_logs.all().delete()  # demo data only: rebuilt on every seed
    athlete.issues.all().delete()
    athlete.programs.all().delete()
    athlete.bodyweights.all().delete()
    BodyweightEntry.objects.create(
        athlete=athlete,
        date=today - datetime.timedelta(days=3),
        kg=units.to_kg(Decimal("182"), "lb"),
        source=MeasurementSource.ATHLETE,
    )
    # Riley's own check-in: the questions on the client's sheet. Recovery goes first because
    # the coach screens summarise the first 1-10 answer as "readiness".
    CheckinQuestion.objects.for_athlete(athlete).delete()
    CheckinQuestion.objects.bulk_create(
        [
            CheckinQuestion(
                athlete=athlete,
                order=1,
                type=QuestionType.SCALE,
                text="Soreness level",
                low_label="not sore",
                high_label="very sore",
                detail_label="Where?",
            ),
            CheckinQuestion(
                athlete=athlete,
                order=0,
                type=QuestionType.SCALE,
                text="Perceived recovery score",
                low_label="not recovered",
                high_label="fully recovered",
            ),
            CheckinQuestion(athlete=athlete, order=2, type=QuestionType.TEXT, text="Other notes"),
        ]
    )
    return athlete


def _program(athlete, template, coach_user, today):
    """The template on Mon/Tue/Thu/Fri, starting two weeks before this one."""
    start = athlete.gym.week_start_for(today) - datetime.timedelta(days=14)
    planned = apply.plan(template, athlete, [0, 1, 3, 4], apply.DEFAULTS)
    program = program_services.start_program(
        athlete, TEMPLATE_NAME, start, 0, planned[0].week_type, by=coach_user
    )
    program.source_template, program.note = template, template.program_note
    program.save(update_fields=["source_template", "note"])
    for order, planned_week in enumerate(planned):
        apply._write_week(
            program, order, start + datetime.timedelta(days=7 * order), planned_week, publish=True
        )
    return program


def _log(athlete, program, today):
    tz = zoneinfo.ZoneInfo(athlete.user.timezone)
    questions = list(CheckinQuestion.objects.for_athlete(athlete).active())
    for week in program.weeks.all()[:3]:
        for day in week.days.filter(date__lt=today).prefetch_related("sessions"):
            for program_session in day.sessions.all():
                done = LOGGED[program_session.name]
                if all(w[week.order] is None for w in done.values()):
                    continue  # never logged (week 1, Day 4)
                log = sessions.start(athlete, program_session)
                for se in log.exercises.all():
                    if se.warmup:
                        se.checked_at = timezone.now()
                        se.save(update_fields=["checked_at"])
                        continue
                    entry = done.get(se.exercise_name, [None] * 3)[week.order]
                    if entry is None:
                        continue
                    load, reps, rirs = entry
                    if isinstance(load, str):  # timed work: one set
                        _r, seconds = parse_rep_scheme(load)
                        SetLog.objects.create(
                            session_exercise=se, set_number=1, duration_seconds=seconds, done=True
                        )
                        continue
                    for n, r in enumerate(reps, start=1):
                        SetLog.objects.create(
                            session_exercise=se,
                            set_number=n,
                            load_kg=units.to_kg(Decimal(load), "lb") if load else None,
                            reps=r,
                            rir=rirs[n - 1] if rirs else None,
                            done=True,
                        )
                checkin = CHECKINS.get((program_session.name, week.order))
                if checkin:
                    soreness, where, recovery, other, rpe, comment = checkin
                    answers = {
                        "Soreness level": (str(soreness), where),
                        "Perceived recovery score": (str(recovery), ""),
                        "Other notes": (other, ""),
                    }
                    for order, q in enumerate(questions):
                        value, detail = answers[q.text]
                        CheckinAnswer.objects.create(
                            session_log=log,
                            question=q,
                            order=order,
                            question_text=q.text,
                            type=q.type,
                            value=value,
                            other_text=detail,
                        )
                else:
                    log.checkin_skipped, rpe, comment = True, 7, ""
                log.started_at = datetime.datetime.combine(day.date, datetime.time(6, 30), tzinfo=tz)
                log.finished_at = log.started_at + datetime.timedelta(minutes=75)
                log.session_rpe, log.comment = rpe, comment
                log.save()
                if program_session.name == "Day 1 — Squat" and week.order == 0:
                    IssueReport.objects.create(
                        athlete=athlete,
                        session_log=log,
                        kind=IssueKind.PAIN,
                        text="Small twinge near the left elbow on DB rows — keeping an eye on it",
                        resolved_at=log.finished_at + datetime.timedelta(days=9),
                    )


def seed_meso(gym, coach, coach_user, today):
    exercises = _exercises(gym)
    template = _template(gym, coach_user, exercises)
    athlete = _athlete(coach, gym, today)
    program = _program(athlete, template, coach_user, today)
    _log(athlete, program, today)
    return athlete
