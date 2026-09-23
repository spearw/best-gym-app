from django.db import migrations

# The fixed lists the app used before categories and tags became per-gym.
OLD_CATEGORIES = [
    ("snatch", "Snatch"), ("clean_jerk", "Clean & Jerk"), ("squat", "Squat"), ("pull", "Pull"),
    ("press", "Press"), ("accessory", "Accessory"), ("conditioning", "Conditioning"), ("mobility", "Mobility"),
]
OLD_TAGS = [
    "high-impact", "low-impact", "competition-lift", "technique", "speed", "strength", "hypertrophy",
    "overhead", "posterior-chain", "unilateral", "no-equipment", "high-CNS", "recovery",
]


def copy(apps, schema_editor):
    Gym = apps.get_model("accounts", "Gym")
    Category = apps.get_model("exercises", "Category")
    Tag = apps.get_model("exercises", "Tag")
    Exercise = apps.get_model("exercises", "Exercise")
    for gym in Gym.objects.all():
        categories = {
            value: Category.objects.create(gym=gym, name=label, order=i)
            for i, (value, label) in enumerate(OLD_CATEGORIES)
        }
        tags = {name: Tag.objects.create(gym=gym, name=name) for name in OLD_TAGS}
        for exercise in Exercise.objects.filter(gym=gym):
            exercise.category_ref = categories[exercise.category]
            exercise.save(update_fields=["category_ref"])
            exercise.tag_set.set([tags[t] for t in exercise.tags if t in tags])


class Migration(migrations.Migration):
    dependencies = [("exercises", "0004_category_and_tag_models"), ("accounts", "0004_maxentry_exercise_and_more")]
    operations = [migrations.RunPython(copy, migrations.RunPython.noop)]
