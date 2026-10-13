from datetime import timedelta

from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import LoginAttempt, RequestReceipt


class Command(BaseCommand):
    help = (
        "Delete expired sessions, old login counters and idempotency receipts "
        "past the safe retry window. Orders, stock moves, reports and corrections stay."
    )

    def handle(self, **options):
        now = timezone.now()
        sessions = Session.objects.filter(expire_date__lt=now).delete()[0]
        attempts = LoginAttempt.objects.filter(
            created_at__lt=now - timedelta(days=1)
        ).delete()[0]
        # Clients may retry the same Idempotency-Key for 7 days. Deleting a key
        # sooner can repeat a shipment, production report or correction.
        receipts = RequestReceipt.objects.filter(
            created_at__lt=now - timedelta(days=7)
        ).delete()[0]
        self.stdout.write(
            f"Removed expired sessions: {sessions}; login counters: {attempts}; "
            f"idempotency receipts older than 7 days: {receipts}."
        )
