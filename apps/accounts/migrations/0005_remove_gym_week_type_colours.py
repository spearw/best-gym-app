from django.db import migrations


class Migration(migrations.Migration):
    """Week type colours now live on each gym's WeekType rows (programs.0002 copied them)."""

    dependencies = [("accounts", "0004_maxentry_exercise_and_more"), ("programs", "0002_copy_week_types")]
    operations = [migrations.RemoveField(model_name="gym", name="week_type_colours")]
