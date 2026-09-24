"""The mockup's library (TPLS, WEEKS and SESSLIB in mockup/index.html) for seed_demo:
five program templates, four saved weeks and five saved sessions. Progressive weeks
are built the way a coach would: "+ Add week" with a percentage bump."""

from decimal import Decimal

from apps.exercises.models import Tag
from apps.library.models import Template, TemplateHabit, TemplateKind, TemplateSession, TemplateWeek
from apps.library.services import add_slot, copy_week
from apps.programs.models import WeekType
from apps.programs.prescriptions import parse_rep_scheme

from ._seed_programs import WEEK_TYPE_NAMES, _load


def slot(key, sets, reps, load, note=""):
    return (key, None, sets, reps, load, note)


def tslot(tags, default, sets, reps, load, note=""):
    return (default, tags, sets, reps, load, note)


ACCUM = [
    (
        "A — Snatch + Squat",
        [
            slot("sn", 6, "2", "70%"),
            slot("snp", 4, "3", "90%"),
            slot("bsq", 5, "5", "70%"),
            tslot(["posterior-chain", "hypertrophy"], "rdl", 3, "8", "—"),
        ],
    ),
    (
        "B — Clean & Jerk + Press",
        [
            slot("cj", 6, "1+1", "70%"),
            slot("cp", 4, "2", "95%"),
            slot("fsq", 4, "3", "72%"),
            tslot(["overhead", "strength"], "pp", 4, "5", "—"),
        ],
    ),
    (
        "C — Speed + Accessory",
        [
            slot("psn", 5, "2", "65%"),
            slot("pc", 5, "2", "65%"),
            tslot(["unilateral"], "bsp", 3, "8/leg", "—"),
            tslot(["no-equipment", "low-impact"], "abw", 3, "12", "BW"),
        ],
    ),
]
INTENS = [
    (
        "A — Snatch heavy",
        [
            slot("sn", 5, "1", "80%"),
            slot("snp", 3, "2", "100%"),
            slot("bsq", 4, "3", "80%"),
            tslot(["posterior-chain"], "rdl", 3, "6", "—"),
        ],
    ),
    (
        "B — Clean & Jerk heavy",
        [
            slot("cj", 5, "1", "82%"),
            slot("cp", 3, "2", "102%"),
            slot("fsq", 3, "2", "82%"),
            tslot(["overhead", "strength"], "pp", 3, "4", "—"),
        ],
    ),
    (
        "C — Complexes",
        [
            slot("hsn", 4, "2", "72%"),
            slot("fj", 4, "2", "78%"),
            tslot(["unilateral"], "bsp", 3, "6/leg", "—"),
        ],
    ),
]
PEAK = [
    (
        "A — Openers",
        [
            slot("sn", 3, "1", "88%", "Build to opener."),
            slot("cj", 3, "1", "88%"),
            slot("bsq", 3, "2", "82%"),
        ],
    ),
    (
        "B — Speed",
        [
            slot("psn", 4, "2", "68%"),
            slot("pc", 4, "2", "68%"),
            tslot(["recovery", "low-impact"], "mob", 1, "10 min", "—"),
        ],
    ),
    (
        "C — Comp simulation",
        [
            slot("sn", 3, "1", "92%", "3 attempts, comp timing."),
            slot("cj", 3, "1", "92%", "3 attempts, comp timing."),
        ],
    ),
]
DELOAD = [
    (
        "A — Bar speed",
        [
            slot("sn", 4, "2", "60%", "Bar speed only."),
            slot("ohs", 3, "3", "40%"),
            tslot(["recovery"], "hips", 1, "10 min", "—"),
        ],
    ),
    (
        "B — Light C&J",
        [slot("cj", 4, "1+1", "62%"), tslot(["recovery", "low-impact"], "bike", 1, "20 min", "—", "Zone 1.")],
    ),
]
TECH = [
    (
        "A — Positions",
        [
            slot("tsn", 5, "3", "55%", "Five seconds up."),
            slot("snb", 4, "3", "60%"),
            slot("ohs", 3, "3", "50%"),
        ],
    ),
    (
        "B — Jerk mechanics",
        [
            slot("hsn", 6, "2", "62%"),
            slot("fj", 5, "2", "65%", "Pause 2s in the dip."),
            tslot(["overhead", "technique"], "snb", 3, "3", "55%"),
        ],
    ),
]
CUT = [
    (
        "A — Sharp singles",
        [
            slot("sn", 5, "1", "78%", "Low volume, keep the CNS sharp."),
            tslot(["recovery", "low-impact"], "mob", 1, "10 min", "—"),
        ],
    ),
    (
        "B — C&J + easy aerobic",
        [slot("cj", 5, "1", "80%"), slot("bike", 1, "25 min", "—", "Zone 2, easy pace.")],
    ),
]


def general(i):
    return [
        (
            "A — Squat + pull",
            [
                slot("bsq", 5, "5", f"{70 + i * 2.5}%"),
                tslot(["posterior-chain", "strength"], "cp", 4, "3", "—"),
                tslot(["unilateral"], "bsp", 3, "8/leg", "—"),
                tslot(["no-equipment"], "abw", 3, "12", "BW"),
            ],
        ),
        (
            "B — Press + pull",
            [
                tslot(["overhead", "strength"], "sp", 5, "5", "—"),
                tslot(["posterior-chain", "hypertrophy"], "row", 4, "8", "—"),
                tslot(["recovery"], "mob", 1, "10 min", "—"),
            ],
        ),
    ]


# name, description, sessions/week, [(week type, sessions, % bump)], habits
TEMPLATES = [
    (
        "12-Week Competition Cycle",
        "Accumulate, intensify, peak for a meet — the standard three-month block",
        3,
        [("accum", ACCUM, b) for b in (0, 2.5, 5, 7.5)]
        + [("intens", INTENS, b) for b in (0, 2, 4, 6)]
        + [("peak", PEAK, b) for b in (0, 2, 3)]
        + [("deload", DELOAD, 0)],
        [
            ("Sleep 8 hours", "😴", "daily", "Recovery is part of the program"),
            ("10-min ankle mobility", "🧘", "training", "Before every session"),
        ],
    ),
    (
        "Accumulation Block (4 wk)",
        "Squat-biased volume build with a deload",
        3,
        [("accum", ACCUM, b) for b in (0, 2.5, 5)] + [("deload", DELOAD, 0)],
        [],
    ),
    (
        "Technique Reset (3 wk)",
        "Tempo work and complexes at or below 70%",
        2,
        [("tech", TECH, b) for b in (0, 3, 6)],
        [],
    ),
    (
        "Weight-Make (2 wk)",
        "Reduced volume, intensity kept, for athletes cutting to a class",
        2,
        [("cut", CUT, b) for b in (0, 2)],
        [
            ("Log bodyweight each morning", "⚖️", "daily", "Before food, after the bathroom"),
            ("3 litres of water", "💧", "daily", ""),
        ],
    ),
    (
        "General Strength — 2 day",
        "Mostly tag-based: accessory slots resolve to whatever each athlete has been doing",
        2,
        [("deload" if i == 3 else "accum", general(i), 0) for i in range(4)],
        [],
    ),
]

WEEKS = [
    (
        "Accumulation — 3 day",
        "Volume week: snatch, C&J and squats with tag-based accessories",
        "accum",
        ACCUM,
    ),
    ("Intensification — 3 day", "Heavy singles and doubles, pulls over 100%", "intens", INTENS),
    ("Deload — 2 day", "Bar speed and easy aerobic work", "deload", DELOAD),
    ("Technique — 2 day", "Tempo pulls, snatch balance, jerk mechanics", "tech", TECH),
]

SESSIONS = [
    ("A — Snatch + Squat", "Accumulation main day", "accum", ACCUM[0][1]),
    ("B — Clean & Jerk + Press", "Accumulation second day", "accum", ACCUM[1][1]),
    ("C — Speed + Accessory", "Light, fast, tag-based accessories", "accum", ACCUM[2][1]),
    ("Openers rehearsal", "Comp-timing singles", "peak", PEAK[2][1]),
    ("Positions (tempo)", "Technique day at light loads", "tech", TECH[0][1]),
]


def _fill(session, items, exercises, tags):
    for key, tag_names, sets, reps, load, note in items:
        s = add_slot(session, exercises[key], tags=[tags[t] for t in tag_names] if tag_names else None)
        basis, value = _load(load)
        s.sets, s.rep_scheme, s.load_basis, s.load_value, s.note = sets, reps, basis, value, note
        s.reps, s.duration_seconds = parse_rep_scheme(reps)
        s.save()


def _week(template, order, week_type, sessions, exercises, tags):
    week = TemplateWeek.objects.create(template=template, order=order, week_type=week_type)
    for i, (name, items) in enumerate(sessions):
        _fill(TemplateSession.objects.create(week=week, order=i, name=name), items, exercises, tags)
    return week


def seed_library(gym, exercises, coach_user):
    Template.objects.filter(gym=gym).delete()  # demo data only: rebuilt on every seed
    week_types = {k: WeekType.objects.get(gym=gym, name=v) for k, v in WEEK_TYPE_NAMES.items()}
    tags = {t.name: t for t in Tag.objects.filter(gym=gym)}
    for name, description, per_week, weeks, habits in TEMPLATES:
        t = Template.objects.create(
            gym=gym,
            kind=TemplateKind.PROGRAM,
            name=name,
            description=description,
            sessions_per_week=per_week,
            created_by=coach_user,
        )
        base = {}
        for order, (type_key, sessions, bump) in enumerate(weeks):
            key = (type_key, id(sessions))
            if key in base and bump:
                copy_week(
                    base[key], t, order, Decimal(str(bump))
                )  # a progressive copy of the block's first week
            else:
                base[key] = _week(t, order, week_types[type_key], sessions, exercises, tags)
        for i, (habit, emoji, cadence, note) in enumerate(habits):
            TemplateHabit.objects.create(
                template=t, order=i, name=habit, emoji=emoji, cadence=cadence, note=note
            )
    for name, description, type_key, sessions in WEEKS:
        t = Template.objects.create(
            gym=gym,
            kind=TemplateKind.WEEK,
            name=name,
            description=description,
            sessions_per_week=len(sessions),
            created_by=coach_user,
        )
        _week(t, 0, week_types[type_key], sessions, exercises, tags)
    for name, description, type_key, items in SESSIONS:
        t = Template.objects.create(
            gym=gym,
            kind=TemplateKind.SESSION,
            name=name,
            description=description,
            sessions_per_week=1,
            created_by=coach_user,
        )
        _week(t, 0, week_types[type_key], [("", items)], exercises, tags)
