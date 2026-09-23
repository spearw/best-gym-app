from django.db import migrations

DEFAULT_TRACKED_KEYS = ["sn", "cj", "bsq"]


def track_defaults(apps, schema_editor):
    """Existing gyms keep tracking the three lifts they were built with."""
    Gym = apps.get_model("accounts", "Gym")
    Exercise = apps.get_model("exercises", "Exercise")
    TrackedLift = apps.get_model("exercises", "TrackedLift")
    for gym in Gym.objects.all():
        if TrackedLift.objects.filter(gym=gym).exists():
            continue
        by_key = {e.key: e for e in Exercise.objects.filter(gym=gym, key__in=DEFAULT_TRACKED_KEYS, archived=False)}
        for order, key in enumerate(k for k in DEFAULT_TRACKED_KEYS if k in by_key):
            TrackedLift.objects.create(gym=gym, exercise=by_key[key], order=order)


class Migration(migrations.Migration):
    dependencies = [("exercises", "0002_tracked_lift")]
    operations = [migrations.RunPython(track_defaults, migrations.RunPython.noop)]
