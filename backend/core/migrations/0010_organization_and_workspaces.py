from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def seed_organization(apps, schema_editor):
    Organization = apps.get_model("core", "Organization")
    Workspace = apps.get_model("core", "Workspace")
    Order = apps.get_model("core", "Order")
    Organization.objects.get_or_create(
        pk=1,
        defaults={"name": "POPME", "default_language": "pl", "theme": "plum"},
    )
    space, _ = Workspace.objects.get_or_create(
        name="POPME",
        defaults={"active": True, "primary": True},
    )
    Order.objects.filter(workspace__isnull=True).update(workspace_id=space.pk)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0009_user_profile"),
    ]

    operations = [
        migrations.CreateModel(
            name="Organization",
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
                ("name", models.CharField(default="POPME", max_length=80)),
                ("default_language", models.CharField(default="pl", max_length=5)),
                ("theme", models.CharField(default="plum", max_length=20)),
            ],
        ),
        migrations.CreateModel(
            name="Workspace",
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
                ("active", models.BooleanField(default=True)),
                ("primary", models.BooleanField(default=False)),
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="workspace",
            constraint=models.UniqueConstraint(
                condition=models.Q(("primary", True)),
                fields=("primary",),
                name="one_primary_workspace",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders",
                to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="current_workspace",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="members",
                to="core.workspace",
            ),
        ),
        migrations.RunPython(seed_organization, migrations.RunPython.noop),
    ]
