from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_profile_orders_filter"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="stockitem",
            name="archived",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="UndoAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=180)),
                ("kind", models.CharField(max_length=40)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="undo_action", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
