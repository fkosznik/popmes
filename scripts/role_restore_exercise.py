"""Exercise the application on the restricted database role.

Used by scripts/backup-restore-full.sh. Does not print passwords.
"""

import hashlib
import io
import os
import sys
import uuid
from datetime import timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection, transaction
from django.db.utils import Error as DatabaseError
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from django.contrib.auth import get_user_model

from core.models import Customer, Label, Order, StockItem, Variant


def current_user():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        return cursor.fetchone()[0]


def deny_ddl(sql):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)
    except DatabaseError:
        return
    raise SystemExit("application role was allowed to change the schema")


def client():
    api = APIClient()
    api.force_login(get_user_model().objects.get(username="admin"))
    return api


def seed():
    if current_user() != "popmes_app":
        raise SystemExit("seed connected as an unexpected role")
    call_command("bootstrap")
    call_command("seed_catalog")
    variant = Variant.objects.get(sku="KAR-30-LOGO")
    customer = Customer.objects.create(
        name="Odtworzenie ról",
        email="role-restore@example.com",
        delivery_addresses=[{"id": "a1", "name": "Sklep", "address": "Testowa 1"}],
    )
    due = (timezone.now() + timedelta(days=2)).isoformat()
    saved = client().post(
        "/api/orders/save/",
        {
            "customer_id": customer.pk,
            "due_at": due,
            "delivery": "courier",
            "delivery_address_id": "a1",
            "confirm": True,
            "items": [{"variant_id": variant.pk, "quantity": 5}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    if saved.status_code != 200:
        raise SystemExit(f"order save failed: {saved.status_code}")
    order = Order.objects.get(pk=saved.data["id"])
    image = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(image, "PNG")
    upload = SimpleUploadedFile("label.png", image.getvalue(), content_type="image/png")
    labeled = client().post(
        f"/api/items/{order.items.get().pk}/labels/",
        {"file": upload},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    if labeled.status_code != 200:
        raise SystemExit(f"label upload failed: {labeled.status_code}")
    approved = client().post(
        f"/api/labels/{labeled.data['id']}/approve/",
        {},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    if approved.status_code != 200:
        raise SystemExit(f"label approve failed: {approved.status_code}")
    stock = (
        StockItem.objects.filter(artwork_unknown=False, artwork_sha256="")
        .order_by("id")
        .first()
    )
    stock.quantity = 42
    stock.save(update_fields=["quantity"])
    deny_ddl("CREATE TABLE popmes_should_fail (id integer)")
    print("seeded order, label and stock")


def verify():
    if current_user() != "popmes_app":
        raise SystemExit("verify connected as an unexpected role")
    order = Order.objects.get()
    detail = client().get(f"/api/orders/{order.pk}/")
    if detail.status_code != 200:
        raise SystemExit(f"order read failed: {detail.status_code}")
    label = Label.objects.get(item__order=order)
    downloaded = client().get(f"/api/labels/{label.pk}/download/")
    if downloaded.status_code != 200:
        raise SystemExit(f"label download failed: {downloaded.status_code}")
    payload = b"".join(downloaded.streaming_content)
    digest = hashlib.sha256(payload).hexdigest()
    if digest != label.content_sha256 or not payload.startswith(b"\x89PNG"):
        raise SystemExit("restored label bytes do not match the stored graphic")
    stock = (
        StockItem.objects.filter(artwork_unknown=False, artwork_sha256="")
        .order_by("id")
        .first()
    )
    if stock.quantity != 42:
        raise SystemExit("restored stock quantity changed")
    held = client().post(
        f"/api/orders/{order.pk}/hold/",
        {"reason": "po odtworzeniu"},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    if held.status_code != 200:
        raise SystemExit(f"order write failed: {held.status_code}")
    order.refresh_from_db()
    if order.hold_reason != "po odtworzeniu":
        raise SystemExit("hold was not stored")
    deny_ddl("CREATE TABLE popmes_should_fail (id integer)")
    print("restored application read, write and label download passed")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "seed":
        seed()
    elif action == "verify":
        verify()
    else:
        raise SystemExit("usage: role_restore_exercise.py seed|verify")
