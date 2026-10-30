import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
def seed_stock(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_packages_and_shipments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=180)),
                ("group", models.CharField(max_length=20)),
                ("unit", models.CharField(max_length=10)),
                (
                    "quantity",
                    models.DecimalField(decimal_places=3, default=0, max_digits=14),
                ),
                ("position", models.PositiveIntegerField(default=0)),
                (
                    "variant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.PROTECT,
                        to="core.variant",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="stockitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(variant__isnull=False),
                fields=("variant",),
                name="one_stock_per_variant",
            ),
        ),
        migrations.CreateModel(
            name="StockMove",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("delta", models.DecimalField(decimal_places=3, max_digits=14)),
                (
                    "quantity_after",
                    models.DecimalField(decimal_places=3, max_digits=14),
                ),
                ("reason", models.TextField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name="moves",
                        to="core.stockitem",
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.PROTECT,
                        to="core.report",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.RunPython(seed_stock, migrations.RunPython.noop),
    ]
