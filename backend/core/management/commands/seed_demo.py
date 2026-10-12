from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from core.models import Customer, Variant, Order, Item
from core import services as s


class Command(BaseCommand):
    help = "Add clearly marked synthetic demo orders once. No additional accounts are created."

    @transaction.atomic
    def handle(self, **options):
        call_command("seed_catalog")
        user = get_user_model().objects.filter(is_superuser=True).first()
        if not user:
            raise CommandError("Run bootstrap first.")
        if Order.objects.filter(internal_notes="POPMES_DEMO_V1").exists():
            self.stdout.write("Demo already exists; skipped.")
            return
        samples = [
            (
                "DEMO · Studio Kreatywne",
                2,
                "normal",
                [("KAR-30-LOGO", 200), ("CZEK-100", 50)],
            ),
            (
                "DEMO · Kawiarnia Poranna",
                1,
                "normal",
                [("BIAL-100", 80), ("ORZ-100", 60)],
            ),
            (
                "DEMO · Jesienny Event",
                0,
                "urgent",
                [("KAR-100", 100), ("CZEK-30", 120)],
            ),
            (
                "DEMO · Sklep Sąsiedzki",
                3,
                "normal",
                [("KAR-100", 40), ("BIAL-100", 40)],
            ),
        ]
        for index, (name, days, priority, lines) in enumerate(samples):
            customer = Customer.objects.create(
                name=name,
                contact="Przykładowy kontakt",
                email=f"demo{index}@example.com",
                delivery_addresses=[
                    {
                        "id": "demo",
                        "name": "Sklep",
                        "address": "ul. Demonstracyjna 1",
                    }
                ],
            )
            order = Order.objects.create(
                created_by=user,
                customer=customer,
                due_at=timezone.now() + timedelta(days=days, hours=4),
                priority=priority,
                delivery="courier",
                address="Sklep\nul. Demonstracyjna 1",
                delivery_address_id="demo",
                internal_notes="POPMES_DEMO_V1",
                packing_notes="Dane demonstracyjne — przykład do testowania.",
            )
            for sku, quantity in lines:
                variant = Variant.objects.select_related("product").get(sku=sku)
                item = Item(order=order, variant=variant, quantity=quantity)
                s.snapshot_item(item, variant)
                item.save()
            s.confirm(order, user)
            if index == 1:
                for task in order.tasks.filter(kind="production"):
                    left = s.to_produce(task.item)
                    if left:
                        s.production_report(task, user, {"units": left})
            if index == 2:
                for task in order.tasks.filter(kind="production"):
                    left = s.to_produce(task.item)
                    if left:
                        s.production_report(
                            task, user, {"units": max(1, left // 2)}
                        )
            if index == 3:
                for task in order.tasks.filter(kind="production"):
                    left = s.to_produce(task.item)
                    if left:
                        s.production_report(task, user, {"units": left})
                for task in order.tasks.filter(kind="shipping"):
                    task.item.refresh_from_db()
                    ready = s.ready_to_ship(task.item)
                    if ready:
                        s.shipping_report(task, user, {"units": ready})
        self.stdout.write("4 synthetic DEMO orders created.")
