from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_organization_and_workspaces"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="appearance",
            field=models.CharField(default="light", max_length=10),
        ),
    ]
