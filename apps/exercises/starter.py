"""Starter packs a new gym chooses at sign-up: categories, tags, week types,
exercises and tracked lifts. Everything they create is the gym's own and editable.

Installing a pack only adds what's missing; it never changes or re-adds something a
coach has edited or removed. Starter exercises carry a `key` purely so installing
twice doesn't duplicate them. Demo links are left blank: coaches add their own.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models.functions import Lower

from apps.programs.models import WeekType

from .models import Category, Exercise, Measure, Tag, TrackedLift

REPS, TIME, DISTANCE = Measure.REPS, Measure.TIME, Measure.DISTANCE


@dataclass(frozen=True)
class Ex:
    key: str
    name: str
    category: str
    tags: tuple = ()
    percent_of: str | None = None  # key of the exercise whose max percentages come from
    measure: str = REPS
    cue: str = ""


@dataclass(frozen=True)
class Pack:
    key: str
    label: str
    description: str
    categories: tuple
    tags: tuple
    week_types: tuple  # (name, description, colour)
    exercises: tuple = ()
    tracked: tuple = ()  # exercise keys, in order
    extra: dict = field(default_factory=dict)


WEIGHTLIFTING = Pack(
    key="weightlifting",
    label="Olympic weightlifting",
    description="Snatch, clean & jerk and their pulls, squats and presses; tracks snatch, C&J, back squat.",
    categories=("Snatch", "Clean & Jerk", "Squat", "Pull", "Press", "Accessory", "Conditioning", "Mobility"),
    tags=(
        "high-impact",
        "low-impact",
        "competition-lift",
        "technique",
        "speed",
        "strength",
        "hypertrophy",
        "overhead",
        "posterior-chain",
        "unilateral",
        "no-equipment",
        "high-CNS",
        "recovery",
    ),
    week_types=(
        ("Accumulation", "Volume build — higher reps, moderate loads", "#2E9E5B"),
        ("Intensification", "Load climbs, volume drops", "#E07C24"),
        ("Comp Prep", "Openers & heavy singles, taper volume", "#D8412F"),
        ("Deload", "Recovery — 60-70% loads, low volume", "#8A63D2"),
        ("Cutting", "Weight-make week — reduced volume, keep intensity", "#2B7DE0"),
        ("Technique", "Positions, tempo & complexes at light loads", "#0F9BA8"),
    ),
    exercises=(
        Ex(
            "sn",
            "Snatch",
            "Snatch",
            ("competition-lift", "high-impact", "high-CNS", "speed"),
            cue="Bar close, finish tall, punch under.",
        ),
        Ex(
            "psn",
            "Power Snatch",
            "Snatch",
            ("speed", "high-impact", "competition-lift"),
            "sn",
            cue="Aggressive extension, catch above parallel.",
        ),
        Ex(
            "hsn",
            "Hang Snatch (knee)",
            "Snatch",
            ("technique", "speed"),
            "sn",
            cue="Load the hamstrings, stay over the bar.",
        ),
        Ex(
            "snp",
            "Snatch Pull",
            "Pull",
            ("strength", "posterior-chain", "high-impact"),
            "sn",
            cue="Match your snatch positions, no early arm bend.",
        ),
        Ex(
            "snb",
            "Snatch Balance",
            "Snatch",
            ("technique", "speed", "overhead"),
            "sn",
            cue="Fast feet, lock as you meet the bar.",
        ),
        Ex(
            "cj",
            "Clean & Jerk",
            "Clean & Jerk",
            ("competition-lift", "high-impact", "high-CNS"),
            cue="Patient off the floor, violent at the hip.",
        ),
        Ex(
            "pc",
            "Power Clean",
            "Clean & Jerk",
            ("speed", "high-impact"),
            "cj",
            cue="Elbows through fast, catch tall.",
        ),
        Ex(
            "fj",
            "Jerk from Blocks",
            "Clean & Jerk",
            ("overhead", "technique", "high-CNS"),
            "cj",
            cue="Vertical dip, split with intent.",
        ),
        Ex(
            "cp",
            "Clean Pull",
            "Pull",
            ("strength", "posterior-chain", "high-impact"),
            "cj",
            cue="Sweep the bar in, shrug at the top.",
        ),
        Ex(
            "bsq",
            "Back Squat",
            "Squat",
            ("strength", "high-impact", "posterior-chain"),
            cue="Big air, drive the floor apart.",
        ),
        Ex(
            "fsq",
            "Front Squat",
            "Squat",
            ("strength", "high-impact"),
            "bsq",
            cue="Elbows up out of the hole.",
        ),
        Ex(
            "psq",
            "Pause Squat (3s)",
            "Squat",
            ("strength", "technique", "hypertrophy"),
            "bsq",
            cue="Own the bottom — no bounce.",
        ),
        Ex(
            "ohs",
            "Overhead Squat",
            "Squat",
            ("overhead", "technique", "low-impact"),
            "bsq",
            cue="Armpits forward, bar over mid-foot.",
        ),
        Ex("pp", "Push Press", "Press", ("overhead", "strength"), cue="Legs start it, arms finish it."),
        Ex(
            "sp",
            "Strict Press",
            "Press",
            ("overhead", "strength", "hypertrophy", "low-impact"),
            cue="Squeeze the glutes, head through.",
        ),
        Ex(
            "rdl",
            "Romanian Deadlift",
            "Accessory",
            ("posterior-chain", "hypertrophy", "low-impact"),
            cue="Hinge, don't squat it.",
        ),
        Ex(
            "bsp",
            "Bulgarian Split Squat",
            "Accessory",
            ("unilateral", "hypertrophy", "low-impact"),
            cue="Front foot far enough forward to stay vertical.",
        ),
        Ex(
            "row",
            "Pendlay Row",
            "Accessory",
            ("strength", "hypertrophy", "posterior-chain"),
            cue="Dead stop each rep, flat back.",
        ),
        Ex(
            "gm",
            "Good Morning",
            "Accessory",
            ("posterior-chain", "hypertrophy", "low-impact"),
            cue="Soft knees, push hips back.",
        ),
        Ex("abw", "Ab Wheel Rollout", "Accessory", ("no-equipment", "low-impact"), cue="Ribs down, no sag."),
        Ex(
            "bike",
            "Bike Erg intervals",
            "Conditioning",
            ("low-impact", "no-equipment", "recovery"),
            measure=TIME,
            cue="Nose-breathing pace unless told otherwise.",
        ),
        Ex(
            "mob",
            "T-spine + Ankle Mobility",
            "Mobility",
            ("recovery", "no-equipment", "low-impact"),
            measure=TIME,
            cue="Two minutes per position, breathe.",
        ),
        Ex(
            "hips",
            "Hip Flow (banded)",
            "Mobility",
            ("recovery", "low-impact"),
            measure=TIME,
            cue="Move slow; this is not a workout.",
        ),
        Ex(
            "tsn",
            "Tempo Snatch DL (5s up)",
            "Pull",
            ("technique", "low-impact", "posterior-chain"),
            "sn",
            cue="Five full seconds — positions over load.",
        ),
    ),
    tracked=("sn", "cj", "bsq"),
)

GENERAL = Pack(
    key="general",
    label="General strength",
    description="Squat, hinge, push, pull, single-leg, core, carries; tracks back squat, bench and deadlift.",
    categories=("Squat", "Hinge", "Push", "Pull", "Single-leg", "Core", "Carry", "Conditioning", "Mobility"),
    tags=(
        "strength",
        "hypertrophy",
        "power",
        "unilateral",
        "bodyweight",
        "no-equipment",
        "machine",
        "low-impact",
        "upper-body",
        "lower-body",
        "posterior-chain",
        "core",
        "recovery",
    ),
    week_types=(
        ("Hypertrophy", "Higher reps, moderate loads — build muscle", "#2E9E5B"),
        ("Strength", "Heavier loads, lower reps", "#E07C24"),
        ("Power", "Fast, explosive work at moderate loads", "#D8412F"),
        ("Deload", "Recovery — lighter loads, less volume", "#8A63D2"),
        ("Testing", "Work up to new maxes", "#2B7DE0"),
    ),
    exercises=(
        Ex(
            "gs_bsq",
            "Back Squat",
            "Squat",
            ("strength", "lower-body"),
            cue="Brace, sit between your hips, drive up.",
        ),
        Ex(
            "gs_fsq",
            "Front Squat",
            "Squat",
            ("strength", "lower-body"),
            "gs_bsq",
            cue="Elbows high, chest up.",
        ),
        Ex(
            "gs_gsq",
            "Goblet Squat",
            "Squat",
            ("hypertrophy", "lower-body", "low-impact"),
            cue="Hold the bell at your chest, elbows inside the knees.",
        ),
        Ex(
            "gs_lp",
            "Leg Press",
            "Squat",
            ("hypertrophy", "lower-body", "machine"),
            cue="Full range without the lower back peeling off the pad.",
        ),
        Ex(
            "gs_dl",
            "Deadlift",
            "Hinge",
            ("strength", "posterior-chain", "lower-body"),
            cue="Push the floor away, bar stays against the legs.",
        ),
        Ex(
            "gs_rdl",
            "Romanian Deadlift",
            "Hinge",
            ("hypertrophy", "posterior-chain", "lower-body"),
            "gs_dl",
            cue="Soft knees, hips back until the hamstrings stretch.",
        ),
        Ex(
            "gs_tbdl",
            "Trap Bar Deadlift",
            "Hinge",
            ("strength", "lower-body"),
            "gs_dl",
            cue="Chest tall, push through the whole foot.",
        ),
        Ex(
            "gs_ht",
            "Hip Thrust",
            "Hinge",
            ("hypertrophy", "posterior-chain", "lower-body"),
            cue="Chin tucked, ribs down, squeeze at the top.",
        ),
        Ex(
            "gs_kbs",
            "Kettlebell Swing",
            "Hinge",
            ("power", "posterior-chain"),
            cue="Snap the hips; the arms just guide the bell.",
        ),
        Ex(
            "gs_bp",
            "Bench Press",
            "Push",
            ("strength", "upper-body"),
            cue="Shoulder blades pinned, feet planted, bar to the lower chest.",
        ),
        Ex(
            "gs_idbp",
            "Incline Dumbbell Press",
            "Push",
            ("hypertrophy", "upper-body"),
            cue="Elbows about 45 degrees, control the stretch.",
        ),
        Ex(
            "gs_ohp",
            "Overhead Press",
            "Push",
            ("strength", "upper-body"),
            cue="Glutes tight, head through at the top.",
        ),
        Ex(
            "gs_pu",
            "Push-up",
            "Push",
            ("bodyweight", "no-equipment", "upper-body"),
            cue="One straight line from head to heels.",
        ),
        Ex(
            "gs_dip",
            "Dip",
            "Push",
            ("bodyweight", "upper-body"),
            cue="Shoulders down, stop at a comfortable depth.",
        ),
        Ex(
            "gs_plu",
            "Pull-up",
            "Pull",
            ("bodyweight", "upper-body"),
            cue="Start from a dead hang, chest to the bar.",
        ),
        Ex(
            "gs_chu",
            "Chin-up",
            "Pull",
            ("bodyweight", "upper-body"),
            cue="Palms facing you, elbows to the ribs.",
        ),
        Ex(
            "gs_row",
            "Barbell Row",
            "Pull",
            ("strength", "upper-body", "posterior-chain"),
            cue="Hinge over, pull to the belly button.",
        ),
        Ex(
            "gs_dbrow",
            "Single-arm Dumbbell Row",
            "Pull",
            ("hypertrophy", "upper-body", "unilateral"),
            cue="Pull the elbow toward the hip, no twisting.",
        ),
        Ex(
            "gs_lpd",
            "Lat Pulldown",
            "Pull",
            ("hypertrophy", "upper-body", "machine"),
            cue="Lead with the elbows, bar to the upper chest.",
        ),
        Ex(
            "gs_fp",
            "Face Pull",
            "Pull",
            ("upper-body", "low-impact"),
            cue="Pull to the forehead, thumbs back.",
        ),
        Ex(
            "gs_bss",
            "Bulgarian Split Squat",
            "Single-leg",
            ("unilateral", "hypertrophy", "lower-body"),
            cue="Front foot far enough forward to stay upright.",
        ),
        Ex(
            "gs_lunge",
            "Walking Lunge",
            "Single-leg",
            ("unilateral", "lower-body"),
            cue="Long stride, back knee kisses the floor.",
        ),
        Ex(
            "gs_stepup",
            "Step-up",
            "Single-leg",
            ("unilateral", "lower-body", "low-impact"),
            cue="Drive through the top foot, don't push off the back one.",
        ),
        Ex(
            "gs_plank",
            "Plank",
            "Core",
            ("core", "no-equipment", "bodyweight"),
            measure=TIME,
            cue="Squeeze glutes, ribs down, breathe.",
        ),
        Ex(
            "gs_deadbug",
            "Dead Bug",
            "Core",
            ("core", "no-equipment", "low-impact"),
            cue="Lower back stays glued to the floor.",
        ),
        Ex(
            "gs_pallof",
            "Pallof Press",
            "Core",
            ("core", "low-impact"),
            cue="Resist the twist, press straight out.",
        ),
        Ex(
            "gs_farmer",
            "Farmer Carry",
            "Carry",
            ("strength", "core"),
            measure=DISTANCE,
            cue="Tall posture, short quick steps.",
        ),
        Ex(
            "gs_bike",
            "Bike intervals",
            "Conditioning",
            ("low-impact", "recovery"),
            measure=TIME,
            cue="Hard efforts hard, easy efforts truly easy.",
        ),
        Ex(
            "gs_row_erg",
            "Rower intervals",
            "Conditioning",
            ("low-impact",),
            measure=TIME,
            cue="Legs, then hips, then arms.",
        ),
        Ex(
            "gs_mob",
            "Hip & Ankle Mobility",
            "Mobility",
            ("recovery", "no-equipment", "low-impact"),
            measure=TIME,
            cue="Slow and controlled, breathe into each position.",
        ),
    ),
    tracked=("gs_bsq", "gs_bp", "gs_dl"),
)

EMPTY = Pack(
    key="empty",
    label="Start empty",
    description="No exercises yet — just a few categories and week types to build from.",
    categories=("Strength", "Accessory", "Conditioning", "Mobility"),
    tags=(),
    week_types=(
        ("Build", "Steady progression", "#2E9E5B"),
        ("Push", "Harder than usual — heavier or more volume", "#E07C24"),
        ("Deload", "Recovery — lighter and less", "#8A63D2"),
    ),
)

PACKS = {p.key: p for p in (WEIGHTLIFTING, GENERAL, EMPTY)}
PACK_CHOICES = [(p.key, p.label) for p in PACKS.values()]


def _get_or_create_named(model, gym, name, **defaults):
    obj = model.objects.filter(gym=gym).annotate(lname=Lower("name")).filter(lname=name.lower()).first()
    return obj or model.objects.create(gym=gym, name=name, **defaults)


@transaction.atomic
def install_pack(gym, pack_key):
    """Add a starter pack's categories, tags, week types, exercises and (if the gym
    tracks none yet) tracked lifts. Only adds what's missing; returns {key: Exercise}."""
    pack = PACKS[pack_key]
    offset = Category.objects.filter(gym=gym).count()
    categories = {
        name: _get_or_create_named(Category, gym, name, order=offset + i)
        for i, name in enumerate(pack.categories)
    }
    tags = {name: _get_or_create_named(Tag, gym, name) for name in pack.tags}
    wt_offset = WeekType.objects.filter(gym=gym).count()
    for i, (name, description, colour) in enumerate(pack.week_types):
        _get_or_create_named(WeekType, gym, name, description=description, colour=colour, order=wt_offset + i)

    by_key, created = {}, set()
    for ex in pack.exercises:
        # Already there, by key or by name (e.g. another pack's Back Squat): leave it alone.
        exercise = (
            Exercise.objects.filter(gym=gym, key=ex.key).first()
            or Exercise.objects.filter(gym=gym, name__iexact=ex.name).first()
        )
        if exercise is None:
            exercise = Exercise.objects.create(
                gym=gym,
                key=ex.key,
                name=ex.name,
                category=categories[ex.category],
                measure=ex.measure,
                cue=ex.cue,
            )
            exercise.tags.set([tags[t] for t in ex.tags])
            created.add(ex.key)
        by_key[ex.key] = exercise
    # Link percentages only for exercises created just now, so a coach's later change sticks.
    for ex in pack.exercises:
        if ex.percent_of and ex.key in created:
            by_key[ex.key].percent_of = by_key[ex.percent_of]
            by_key[ex.key].save(update_fields=["percent_of"])

    if pack.tracked and not TrackedLift.objects.filter(gym=gym).exists():
        TrackedLift.objects.bulk_create(
            [
                TrackedLift(gym=gym, exercise=by_key[k], order=i)
                for i, k in enumerate(k for k in pack.tracked if not by_key[k].archived)
            ]
        )
    return by_key
