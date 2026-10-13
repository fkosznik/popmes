import importlib

from django.db import migrations

separate_legacy_logo_stock = importlib.import_module(
    "core.migrations.0012_artwork_lots"
).separate_legacy_logo_stock


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_indexes_and_login_attempts"),
    ]

    operations = [
        # Runs after 0012 commits its indexes. PostgreSQL cannot build those
        # indexes in the same transaction as the stock rows this step inserts.
        migrations.RunPython(separate_legacy_logo_stock, migrations.RunPython.noop),
    ]
