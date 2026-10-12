from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("core", "0006_stock_categories_and_shipping"),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
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
                ("name", models.CharField(max_length=180, unique=True)),
                ("contact", models.CharField(blank=True, max_length=180)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("active", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="Recipe",
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
                (
                    "variant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recipe",
                        to="core.variant",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="RecipeLine",
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
                (
                    "quantity",
                    models.DecimalField(decimal_places=3, max_digits=14),
                ),
                (
                    "recipe",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="core.recipe",
                    ),
                ),
                (
                    "stock",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recipe_lines",
                        to="core.stockitem",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="recipeline",
            constraint=models.UniqueConstraint(
                fields=("recipe", "stock"), name="one_ingredient_per_recipe"
            ),
        ),
        migrations.AddConstraint(
            model_name="recipeline",
            constraint=models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="recipe_line_positive"
            ),
        ),
        migrations.AddField(
            model_name="stockitem",
            name="supplier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="materials",
                to="core.supplier",
            ),
        ),
    ]
