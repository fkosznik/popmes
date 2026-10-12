import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Sum


def seed_stock(apps, schema_editor):
    StockItem = apps.get_model("core", "StockItem")
    Variant = apps.get_model("core", "Variant")
    Item = apps.get_model("core", "Item")
    materials = [
        ("CUKIER", "Cukier", "ingredient", "kg", 10),
        ("MASLO", "Masło", "ingredient", "kg", 20),
        ("SOL", "Sól", "ingredient", "kg", 30),
        ("SYROP", "Syrop glukozowy", "ingredient", "kg", 40),
    ]
    for grams in (15, 30, 100, 400):
        materials.append(
            (f"OPAK-{grams}", f"Opakowanie {grams} g", "packaging", "szt", grams)
        )
        materials.append(
            (
                f"ETY-{grams}-PRZOD",
                f"Etykieta {grams} g — przód",
                "label",
                "szt",
                grams * 10 + 1,
            )
        )
        materials.append(
            (
                f"ETY-{grams}-TYL",
                f"Etykieta {grams} g — tył",
                "label",
                "szt",
                grams * 10 + 2,
            )
        )
    for code, name, group, unit, position in materials:
        StockItem.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "group": group,
                "unit": unit,
                "position": position,
            },
        )
    for variant in Variant.objects.filter(active=True):
        weight = variant.weight_g
        label = str(int(weight)) if weight == int(weight) else format(weight, "f")
        stock, _ = StockItem.objects.get_or_create(
            code=f"POP-{variant.sku}",
            defaults={
                "name": f"{variant.name} · {label} g",
                "group": "popcorn",
                "unit": "szt",
                "position": int(weight),
                "variant": variant,
            },
        )
        total = (
            Item.objects.filter(variant=variant).aggregate(
                q=Sum(F("produced") - F("packed"))
            )["q"]
            or 0
        )
        stock.quantity = total
        stock.save(update_fields=["quantity"])


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
