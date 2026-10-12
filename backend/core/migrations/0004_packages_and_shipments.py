import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def copy_produced_from_packed(apps, schema_editor):
    Item = apps.get_model("core", "Item")
    for item in Item.objects.filter(packed__gt=0).iterator():
        item.produced = item.packed
        item.save(update_fields=["produced"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_existing_addresses_and_surplus"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="produced",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(copy_produced_from_packed, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(produced__lte=models.F("quantity")),
                name="item_produced_lte_qty",
            ),
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(packed__lte=models.F("produced")),
                name="item_packed_lte_produced",
            ),
        ),
        migrations.AlterField(
            model_name="task",
            name="item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tasks",
                to="core.item",
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(
                condition=models.Q(item__isnull=False),
                fields=("kind", "item"),
                name="one_task_per_item_kind",
            ),
        ),
        migrations.CreateModel(
            name="Shipment",
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
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("address", models.TextField(blank=True)),
                ("note", models.TextField(blank=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shipments",
                        to="core.order",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ShipmentLine",
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
                ("units", models.PositiveIntegerField()),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shipment_lines",
                        to="core.item",
                    ),
                ),
                (
                    "report",
                    models.OneToOneField(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shipment_line",
                        to="core.report",
                    ),
                ),
                (
                    "shipment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="core.shipment",
                    ),
                ),
            ],
        ),
    ]
