"""The mockup's programs (PROGRAMS in mockup/index.html) for seed_demo.

Each athlete's program is laid out so the mockup's "current" week contains today;
weeks up to and including the current one are published. The mockup's week has its
"today" on Tuesday, so each mockup day is placed relative to the real today: Monday's
session is yesterday, Tuesday's is today, and so on (a day that falls outside the
program is left out)."""

import datetime
from decimal import Decimal

from apps.programs import services
from apps.programs.models import LoadBasis, Prescription, ProgramDay, WeekType
from apps.programs.prescriptions import parse_rep_scheme

WEEK_TYPE_NAMES = {
    "accum": "Accumulation",
    "intens": "Intensification",
    "peak": "Comp Prep",
    "deload": "Deload",
    "cut": "Cutting",
    "tech": "Technique",
}


# The mockup's "Coach's focus this week" card.
FOCUS_NOTES = {
    "maya@ironridge.example": "Openers Saturday. Keep every snatch above 90% crisp — cut the set if the bar "
    "drifts forward. Sleep is part of the program this week.",
}

MOCKUP_TODAY = 1  # the mockup's "today" is the Tuesday of its week


def rx(key, sets, reps, load, note="", custom=None):
    return (key, sets, reps, load, note, custom or [])


# email: (block name, current week index, week types, {weekday index: [prescriptions]})
PROGRAMS = {
    "maya@ironridge.example": (
        "Comp Prep Block",
        2,
        ["accum", "intens", "peak", "peak", "deload", "peak"],
        {
            0: [
                rx("sn", 6, "2", "78%", "No misses. Bar stays close."),
                rx("snp", 4, "3", "95%"),
                rx("bsq", 5, "3", "80%"),
                rx("abw", 3, "10", "BW"),
            ],
            1: [
                rx(
                    "cj",
                    6,
                    "1+1",
                    "80%",
                    "Openers mindset — make every one.",
                    [("Rest", "3 min"), ("Bar", "comp bar")],
                ),
                rx("cp", 4, "2", "98%"),
                rx("fsq", 3, "2", "82%"),
            ],
            3: [
                rx("psn", 5, "2", "70%", "Speed day. Move it."),
                rx("snb", 4, "2", "65%"),
                rx("pp", 4, "4", "70%"),
                rx("mob", 1, "10 min", "—"),
            ],
            4: [
                rx("sn", 5, "1", "83%", "Build to opener."),
                rx("cj", 4, "1", "85%"),
                rx("bsq", 3, "2", "85%"),
            ],
            5: [
                rx("sn", 3, "1", "90%", "Comp simulation — 3 attempts."),
                rx("cj", 3, "1", "90%", "3 attempts, comp timing."),
            ],
        },
    ),
    "jonas@ironridge.example": (
        "Intensification Block",
        1,
        ["accum", "intens", "intens", "deload"],
        {
            0: [rx("sn", 6, "2", "75%"), rx("bsq", 5, "4", "78%")],
            1: [
                rx("cj", 5, "1", "82%", "Skip jerks if shoulder pinches — cleans only."),
                rx("cp", 4, "2", "100%"),
            ],
            2: [rx("bike", 1, "20 min", "—", "Zone 2."), rx("mob", 1, "15 min", "—")],
            3: [rx("psn", 5, "2", "68%"), rx("fj", 5, "2", "75%"), rx("rdl", 3, "8", "—")],
            5: [rx("sn", 5, "1", "85%"), rx("cj", 4, "1", "87%"), rx("bsq", 3, "3", "84%")],
        },
    ),
    "marcus@ironridge.example": (
        "Weight-Make Block",
        0,
        ["cut"],
        {
            0: [rx("sn", 5, "1", "78%", "Low volume, keep the CNS sharp."), rx("mob", 1, "10 min", "—")],
            1: [rx("cj", 5, "1", "80%"), rx("bike", 1, "25 min", "—", "Fasted, easy pace.")],
            3: [rx("psn", 4, "2", "70%"), rx("fsq", 3, "2", "75%")],
            5: [rx("sn", 4, "1", "82%"), rx("cj", 3, "1", "84%")],
        },
    ),
    "priya@ironridge.example": (
        "Accumulation Block",
        0,
        ["accum", "accum", "accum", "deload"],
        {
            0: [rx("hsn", 5, "3", "65%"), rx("bsq", 5, "5", "72%"), rx("row", 3, "8", "—")],
            1: [rx("pc", 5, "3", "70%"), rx("sp", 4, "6", "—"), rx("abw", 3, "12", "BW")],
            3: [rx("sn", 6, "2", "70%"), rx("psq", 4, "3", "70%"), rx("gm", 3, "8", "—")],
            5: [rx("cj", 5, "2", "72%"), rx("fsq", 4, "4", "75%"), rx("bsp", 3, "8/leg", "—")],
        },
    ),
    "lena@ironridge.example": (
        "Recovery Week",
        0,
        ["deload"],
        {
            0: [
                rx("sn", 4, "2", "60%", "Bar speed only."),
                rx("ohs", 3, "3", "40%"),
                rx("hips", 1, "10 min", "—"),
            ],
            2: [rx("cj", 4, "1+1", "62%"), rx("mob", 1, "15 min", "—")],
            4: [rx("psn", 4, "2", "55%"), rx("bike", 1, "20 min", "—", "Zone 1.")],
        },
    ),
    "theo@ironridge.example": (
        "Technique Reset",
        0,
        ["tech"],
        {
            0: [
                rx("tsn", 5, "3", "55%", "Five seconds up. Every rep filmed.", [("Tempo", "5-0-X")]),
                rx("snb", 4, "3", "60%"),
                rx("ohs", 3, "3", "50%"),
            ],
            1: [rx("hsn", 6, "2", "62%"), rx("fj", 5, "2", "65%", "Pause 2s in the dip.")],
            3: [rx("sn", 6, "2", "68%", "Only as heavy as positions allow."), rx("psq", 4, "3", "65%")],
            5: [rx("cj", 5, "1+2", "70%"), rx("cp", 4, "3", "85%")],
        },
    ),
}


def _load(text):
    text = text.strip()
    if text.endswith("%"):
        return LoadBasis.PERCENT, Decimal(text[:-1])
    if text == "BW":
        return LoadBasis.BODYWEIGHT, None
    return LoadBasis.NONE, None


def seed_programs(athletes_by_email, exercises, coach_user, today):
    for email, (name, current, types, days) in PROGRAMS.items():
        athlete = athletes_by_email[email]
        athlete.programs.all().delete()  # demo data only: rebuilt on every seed
        week_types = {wt.name: wt for wt in WeekType.objects.filter(gym=athlete.gym)}
        first_week = athlete.gym.week_start_for(today) - datetime.timedelta(weeks=current)
        program = services.start_program(
            athlete, name, first_week, 1, week_types[WEEK_TYPE_NAMES[types[0]]], by=coach_user
        )
        for key in types[1:]:
            services.add_week(program, week_types[WEEK_TYPE_NAMES[key]])
        weeks = list(program.weeks.all())
        for week in weeks[: current + 1]:
            services.set_published(week, True)
        if email in FOCUS_NOTES:
            weeks[current].focus_note = FOCUS_NOTES[email]
            weeks[current].save(update_fields=["focus_note"])
        by_date = {d.date: d for d in ProgramDay.objects.filter(week__program=program)}
        for index, items in days.items():
            day = by_date.get(today + datetime.timedelta(days=index - MOCKUP_TODAY))
            if day is None:
                continue
            session = services.session_for(day)
            for order, (key, sets, reps, load, note, custom) in enumerate(items):
                basis, value = _load(load)
                parsed_reps, duration = parse_rep_scheme(reps)
                Prescription.objects.create(
                    session=session,
                    order=order,
                    exercise=exercises[key],
                    sets=sets,
                    rep_scheme=reps,
                    reps=parsed_reps,
                    duration_seconds=duration,
                    load_basis=basis,
                    load_value=value,
                    note=note,
                    custom_fields=[{"key": k, "value": v} for k, v in custom],
                )
