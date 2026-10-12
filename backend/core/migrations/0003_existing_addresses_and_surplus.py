from decimal import Decimal
from django.db import migrations


def migrate_data(apps, schema_editor):
    Customer = apps.get_model("core", "Customer")
    Order = apps.get_model("core", "Order")
    Batch = apps.get_model("core", "Batch")
    Movement = apps.get_model("core", "Movement")
    for customer in Customer.objects.exclude(address="").iterator():
        customer.delivery_addresses = [
            {"id": "legacy", "name": "Adres główny", "address": customer.address}
        ]
        customer.save(update_fields=["delivery_addresses"])
    for order in Order.objects.all().iterator():
        if order.customer_id:
            c = Customer.objects.get(pk=order.customer_id)
            if order.address:
                addresses = c.delivery_addresses
                address = next(
                    (a for a in addresses if a["address"] == order.address), None
                )
                if not address:
                    address = {
                        "id": f"legacy-order-{order.pk}",
                        "name": "Adres z zamówienia",
                        "address": order.address,
                    }
                    addresses.append(address)
                    c.delivery_addresses = addresses
                    c.save(update_fields=["delivery_addresses"])
                order.delivery_address_id = address["id"]
                order.save(update_fields=["delivery_address_id"])
        for pid in order.batches.values_list("product_id", flat=True).distinct():
            needed = (
                Decimal(0)
                if order.cancelled_at
                else sum(
                    (
                        (i.quantity - i.packed) * i.weight_g
                        for i in order.items.filter(product_id=pid)
                    ),
                    Decimal(0),
                )
            )
            for batch in order.batches.filter(
                product_id=pid, available_g__gt=0
            ).order_by("created_at", "pk"):
                reserved = min(needed, batch.available_g)
                extra = batch.available_g - reserved
                needed -= reserved
                if extra:
                    batch.available_g = reserved
                    batch.save(update_fields=["available_g"])
                    free = Batch.objects.create(
                        origin_id=batch.origin_id,
                        product_id=pid,
                        created_at=batch.created_at,
                        available_g=extra,
                    )
                    Movement.objects.create(
                        batch=batch,
                        order=order,
                        user_id=order.created_by_id,
                        delta_g=-extra,
                        reason="Migracja nadwyżki do wolnego magazynu",
                    )
                    Movement.objects.create(
                        batch=free,
                        user_id=order.created_by_id,
                        delta_g=extra,
                        reason=f"Nadwyżka z partii #{batch.pk}",
                    )


class Migration(migrations.Migration):
    dependencies = [("core", "0002_customer_delivery_addresses_and_more")]
    operations = [migrations.RunPython(migrate_data)]
