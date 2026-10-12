from django.db import migrations, models


def arrange_warehouse(apps, schema_editor):
    StockCategory = apps.get_model("core", "StockCategory")
    StockItem = apps.get_model("core", "StockItem")
    Item = apps.get_model("core", "Item")
    Task = apps.get_model("core", "Task")

    products = StockCategory.objects.create(name="Produkty", position=0, system=True)
    groups = {
        "ingredient": StockCategory.objects.create(name="Półprodukty", position=10),
        "packaging": StockCategory.objects.create(name="Opakowania", position=20),
        "label": StockCategory.objects.create(name="Etykiety", position=30),
        "popcorn": products,
    }
    for item in StockItem.objects.all():
        item.category = groups.get(item.group, products if item.variant_id else None)
        item.save(update_fields=["category"])

    Task.objects.filter(kind="packing").update(kind="shipping")
    held = {}
    open_items = Item.objects.select_related("order", "product").filter(
        order__confirmed_at__isnull=False,
        order__cancelled_at__isnull=True,
        order__issued_at__isnull=True,
    )
    for item in open_items:
        if item.packed < item.quantity and not Task.objects.filter(
            kind="shipping", item=item
        ).exists():
            Task.objects.create(
                order=item.order,
                kind="shipping",
                product=item.product,
                product_name=item.name,
                item=item,
                instruction=item.instruction,
            )
        if item.variant_id and item.produced > item.packed:
            held[item.variant_id] = held.get(item.variant_id, 0) + (
                item.produced - item.packed
            )
    for variant_id, units in held.items():
        stock = StockItem.objects.filter(variant_id=variant_id).first()
        if not stock:
            continue
        stock.reserved = min(stock.quantity, units)
        stock.save(update_fields=["reserved"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0005_warehouse_stock"),
    ]

    operations = [
        migrations.CreateModel(
            name="StockCategory",
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
                ("name", models.CharField(max_length=80, unique=True)),
                ("position", models.PositiveIntegerField(default=0)),
                ("system", models.BooleanField(default=False)),
            ],
        ),
        migrations.AddField(
            model_name="item",
            name="allocated",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="stockitem",
            name="reserved",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="stockitem",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="items",
                to="core.stockcategory",
            ),
        ),
        migrations.AddField(
            model_name="stockmove",
            name="reserved_delta",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=14),
        ),
        migrations.RemoveConstraint(
            model_name="item",
            name="item_packed_lte_produced",
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(allocated__lte=models.F("quantity")),
                name="item_allocated_lte_qty",
            ),
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    produced__lte=models.F("quantity") - models.F("allocated")
                ),
                name="item_covered_lte_qty",
            ),
        ),
        migrations.AddConstraint(
            model_name="item",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    packed__lte=models.F("allocated") + models.F("produced")
                ),
                name="item_shipped_lte_ready",
            ),
        ),
        migrations.RunPython(arrange_warehouse, migrations.RunPython.noop),
    ]
