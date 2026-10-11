import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from core.services import ROLES


class Command(BaseCommand):
    help = "Create roles and the initial administrator from environment, without resetting existing passwords."

    def handle(self, **options):
        for role in ROLES:
            Group.objects.get_or_create(name=role)
        username = os.environ.get("ADMIN_USERNAME", "admin")
        if not get_user_model().objects.filter(username=username).exists():
            password = os.environ.get("ADMIN_PASSWORD", "")
            if not password:
                raise CommandError("Set ADMIN_PASSWORD before first startup.")
            validate_password(password)
            user = get_user_model().objects.create_superuser(
                username, password=password, first_name="Filip"
            )
            user.groups.set(Group.objects.filter(name__in=ROLES))
            self.stdout.write("Administrator created. Password is not logged.")
        self.stdout.write("Bootstrap complete.")
