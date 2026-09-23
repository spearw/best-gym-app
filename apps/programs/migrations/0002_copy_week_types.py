from django.db import migrations

# The fixed week types the app used before they became per-gym, with their default colours.
OLD_WEEK_TYPES = [
    ("accum", "Accumulation", "Volume build — higher reps, moderate loads", "#2E9E5B"),
    ("intens", "Intensification", "Load climbs, volume drops", "#E07C24"),
    ("peak", "Comp Prep", "Openers & heavy singles, taper volume", "#D8412F"),
    ("deload", "Deload", "Recovery — 60-70% loads, low volume", "#8A63D2"),
    ("cut", "Cutting", "Weight-make week — reduced volume, keep intensity", "#2B7DE0"),
    ("tech", "Technique", "Positions, tempo & complexes at light loads", "#0F9BA8"),
]


def copy(apps, schema_editor):
    Gym = apps.get_model("accounts", "Gym")
    WeekType = apps.get_model("programs", "WeekType")
    for gym in Gym.objects.all():
        overrides = gym.week_type_colours or {}
        for i, (key, name, description, colour) in enumerate(OLD_WEEK_TYPES):
            WeekType.objects.create(gym=gym, name=name, description=description,
                                    colour=overrides.get(key, colour).upper(), order=i)


class Migration(migrations.Migration):
    dependencies = [("programs", "0001_initial"), ("accounts", "0004_maxentry_exercise_and_more")]
    operations = [migrations.RunPython(copy, migrations.RunPython.noop)]
