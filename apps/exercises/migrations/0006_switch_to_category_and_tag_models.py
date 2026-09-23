import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exercises", "0005_copy_categories_and_tags")]
    operations = [
        migrations.RemoveField(model_name="exercise", name="category"),
        migrations.RemoveField(model_name="exercise", name="tags"),
        migrations.RenameField(model_name="exercise", old_name="category_ref", new_name="category"),
        migrations.RenameField(model_name="exercise", old_name="tag_set", new_name="tags"),
        migrations.AlterField(
            model_name="exercise",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="exercises", to="exercises.category"
            ),
        ),
    ]
