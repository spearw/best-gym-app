"""The starter exercise library every new gym gets: the mockup's 24 exercises.

Keys are stable ids code can rely on (onboarding asks for the sn, cj and bsq maxes).
`percent_of` names the max a percentage load is worked from; None means the
exercise's own max (or, for accessories with no max, loads show as written)."""

from django.db import transaction

from .models import Category, Exercise

C = Category
# key, name, category, tags, percent_of key, measure, youtube, cue
STARTER_EXERCISES = [
    (
        "sn",
        "Snatch",
        C.SNATCH,
        ["competition-lift", "high-impact", "high-CNS", "speed"],
        None,
        "reps",
        "https://youtube.com/watch?v=dsn01",
        "Bar close, finish tall, punch under.",
    ),
    (
        "psn",
        "Power Snatch",
        C.SNATCH,
        ["speed", "high-impact", "competition-lift"],
        "sn",
        "reps",
        "https://youtube.com/watch?v=dsn02",
        "Aggressive extension, catch above parallel.",
    ),
    (
        "hsn",
        "Hang Snatch (knee)",
        C.SNATCH,
        ["technique", "speed"],
        "sn",
        "reps",
        "https://youtube.com/watch?v=dsn03",
        "Load the hamstrings, stay over the bar.",
    ),
    (
        "snp",
        "Snatch Pull",
        C.PULL,
        ["strength", "posterior-chain", "high-impact"],
        "sn",
        "reps",
        "https://youtube.com/watch?v=dpl01",
        "Match your snatch positions, no early arm bend.",
    ),
    (
        "snb",
        "Snatch Balance",
        C.SNATCH,
        ["technique", "speed", "overhead"],
        "sn",
        "reps",
        "https://youtube.com/watch?v=dsn04",
        "Fast feet, lock as you meet the bar.",
    ),
    (
        "cj",
        "Clean & Jerk",
        C.CLEAN_JERK,
        ["competition-lift", "high-impact", "high-CNS"],
        None,
        "reps",
        "https://youtube.com/watch?v=dcj01",
        "Patient off the floor, violent at the hip.",
    ),
    (
        "pc",
        "Power Clean",
        C.CLEAN_JERK,
        ["speed", "high-impact"],
        "cj",
        "reps",
        "https://youtube.com/watch?v=dcj02",
        "Elbows through fast, catch tall.",
    ),
    (
        "fj",
        "Jerk from Blocks",
        C.CLEAN_JERK,
        ["overhead", "technique", "high-CNS"],
        "cj",
        "reps",
        "https://youtube.com/watch?v=dcj03",
        "Vertical dip, split with intent.",
    ),
    (
        "cp",
        "Clean Pull",
        C.PULL,
        ["strength", "posterior-chain", "high-impact"],
        "cj",
        "reps",
        "https://youtube.com/watch?v=dpl02",
        "Sweep the bar in, shrug at the top.",
    ),
    (
        "bsq",
        "Back Squat",
        C.SQUAT,
        ["strength", "high-impact", "posterior-chain"],
        None,
        "reps",
        "https://youtube.com/watch?v=dsq01",
        "Big air, drive the floor apart.",
    ),
    (
        "fsq",
        "Front Squat",
        C.SQUAT,
        ["strength", "high-impact"],
        "bsq",
        "reps",
        "https://youtube.com/watch?v=dsq02",
        "Elbows up out of the hole.",
    ),
    (
        "psq",
        "Pause Squat (3s)",
        C.SQUAT,
        ["strength", "technique", "hypertrophy"],
        "bsq",
        "reps",
        "https://youtube.com/watch?v=dsq03",
        "Own the bottom — no bounce.",
    ),
    (
        "ohs",
        "Overhead Squat",
        C.SQUAT,
        ["overhead", "technique", "low-impact"],
        "bsq",
        "reps",
        "https://youtube.com/watch?v=dsq04",
        "Armpits forward, bar over mid-foot.",
    ),
    (
        "pp",
        "Push Press",
        C.PRESS,
        ["overhead", "strength"],
        None,
        "reps",
        "https://youtube.com/watch?v=dpr01",
        "Legs start it, arms finish it.",
    ),
    (
        "sp",
        "Strict Press",
        C.PRESS,
        ["overhead", "strength", "hypertrophy", "low-impact"],
        None,
        "reps",
        "https://youtube.com/watch?v=dpr02",
        "Squeeze the glutes, head through.",
    ),
    (
        "rdl",
        "Romanian Deadlift",
        C.ACCESSORY,
        ["posterior-chain", "hypertrophy", "low-impact"],
        None,
        "reps",
        "https://youtube.com/watch?v=dac01",
        "Hinge, don't squat it.",
    ),
    (
        "bsp",
        "Bulgarian Split Squat",
        C.ACCESSORY,
        ["unilateral", "hypertrophy", "low-impact"],
        None,
        "reps",
        "https://youtube.com/watch?v=dac02",
        "Front foot far enough forward to stay vertical.",
    ),
    (
        "row",
        "Pendlay Row",
        C.ACCESSORY,
        ["strength", "hypertrophy", "posterior-chain"],
        None,
        "reps",
        "https://youtube.com/watch?v=dac03",
        "Dead stop each rep, flat back.",
    ),
    (
        "gm",
        "Good Morning",
        C.ACCESSORY,
        ["posterior-chain", "hypertrophy", "low-impact"],
        None,
        "reps",
        "https://youtube.com/watch?v=dac04",
        "Soft knees, push hips back.",
    ),
    (
        "abw",
        "Ab Wheel Rollout",
        C.ACCESSORY,
        ["no-equipment", "low-impact"],
        None,
        "reps",
        "https://youtube.com/watch?v=dac05",
        "Ribs down, no sag.",
    ),
    (
        "bike",
        "Bike Erg intervals",
        C.CONDITIONING,
        ["low-impact", "no-equipment", "recovery"],
        None,
        "time",
        "https://youtube.com/watch?v=dcn01",
        "Nose-breathing pace unless told otherwise.",
    ),
    (
        "mob",
        "T-spine + Ankle Mobility",
        C.MOBILITY,
        ["recovery", "no-equipment", "low-impact"],
        None,
        "time",
        "https://youtube.com/watch?v=dmb01",
        "Two minutes per position, breathe.",
    ),
    (
        "hips",
        "Hip Flow (banded)",
        C.MOBILITY,
        ["recovery", "low-impact"],
        None,
        "time",
        "https://youtube.com/watch?v=dmb02",
        "Move slow; this is not a workout.",
    ),
    (
        "tsn",
        "Tempo Snatch DL (5s up)",
        C.PULL,
        ["technique", "low-impact", "posterior-chain"],
        "sn",
        "reps",
        "https://youtube.com/watch?v=dpl03",
        "Five full seconds — positions over load.",
    ),
]

# A new gym starts out tracking these lifts (Settings › Tracked lifts). Only a
# starting point: after that the gym's TrackedLift rows are the source of truth.
DEFAULT_TRACKED_KEYS = ["sn", "cj", "bsq"]


@transaction.atomic
def install_starter_library(gym):
    """Create (or refresh) the starter exercises for a gym. Safe to run repeatedly;
    it never touches exercises a coach created, and never un-archives anything."""
    by_key = {}
    for key, name, category, tags, _percent_of, measure, youtube, cue in STARTER_EXERCISES:
        exercise, _ = Exercise.objects.update_or_create(
            gym=gym,
            key=key,
            defaults={
                "name": name,
                "category": category,
                "tags": tags,
                "measure": measure,
                "youtube_url": youtube,
                "cue": cue,
            },
        )
        by_key[key] = exercise
    for key, *_rest in STARTER_EXERCISES:
        percent_of_key = _rest[3]
        target = by_key[percent_of_key] if percent_of_key else None
        if by_key[key].percent_of_id != (target.pk if target else None):
            by_key[key].percent_of = target
            by_key[key].save(update_fields=["percent_of"])
    return by_key


def track_default_lifts(gym):
    """Give a gym the default tracked lifts, unless it already has a list."""
    from .models import TrackedLift

    if TrackedLift.objects.filter(gym=gym).exists():
        return
    by_key = {
        e.key: e for e in Exercise.objects.filter(gym=gym, key__in=DEFAULT_TRACKED_KEYS, archived=False)
    }
    TrackedLift.objects.bulk_create(
        [
            TrackedLift(gym=gym, exercise=by_key[k], order=i)
            for i, k in enumerate(k for k in DEFAULT_TRACKED_KEYS if k in by_key)
        ]
    )
