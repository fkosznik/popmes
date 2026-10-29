from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_order_workspace_due"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="orders_filter",
            field=models.CharField(default="all", max_length=32),
        ),
    ]
