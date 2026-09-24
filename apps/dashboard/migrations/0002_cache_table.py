"""The database cache's table (settings.CACHES), used for rate-limit counts. A migration,
so it exists wherever migrations run: Render's pre-deploy step, local set-up and tests."""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0001_initial")]

    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
