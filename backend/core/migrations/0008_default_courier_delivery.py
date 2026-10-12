from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_recipes_and_suppliers"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="delivery",
            field=models.CharField(default="courier", max_length=15),
        ),
    ]
