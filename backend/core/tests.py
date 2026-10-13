import io
import json
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from PIL import Image
from .models import (
    Batch,
    Product,
    Variant,
    Customer,
    Order,
    Item,
    Report,
    WorkSession,
    Correction,
    Label,
)
from . import services as s


class FlowTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            "admin", password="Test-password-123!"
        )
        self.client = APIClient()
        self.client.force_login(self.admin)
        self.product = Product.objects.create(code="KAR", name="Karmel")
        self.variant = Variant.objects.create(
            product=self.product, sku="KAR30", name="Karmel 30", weight_g=30
        )
        self.customer = Customer.objects.create(
            name="Firma testowa",
            email="private@example.com",
            delivery_addresses=[
                {"id": "a1", "name": "Sklep", "address": "Testowa 1"}
            ],
        )
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media.cleanup)

    def post(self, path, data=None, key=None, expected=200):
        response = self.client.post(
            "/api/" + path,
            data or {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(key or uuid.uuid4()),
        )
        self.assertEqual(response.status_code, expected, response.content)
        return response

    def order(self, quantity=200, custom=False, confirm=True, pickup=False):
        self.variant.custom_label = custom
        self.variant.save()
        payload = {
            "customer_id": self.customer.pk,
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "items": [{"variant_id": self.variant.pk, "quantity": quantity}],
            "confirm": confirm,
        }
        if pickup:
            payload["delivery"] = "pickup"
        else:
            payload["delivery"] = "courier"
            payload["delivery_address_id"] = "a1"
        r = self.post("orders/save/", payload)
        return Order.objects.get(pk=r.data["id"])

    def tasks(self, order):
        return order.tasks.get(kind="production"), order.tasks.get(kind="shipping")

    def png(self, color="red"):
        out = io.BytesIO()
        Image.new("RGB", (5, 5), color).save(out, "PNG")
        out.seek(0)
        out.name = "label.png"
        return out

    def upload(self, item, color="red"):
        r = self.client.post(
            f"/api/items/{item.pk}/labels/",
            {"file": self.png(color)},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["id"]

    def test_partial_full_flow_and_idempotency(self):
        order = self.order()
        p, k = self.tasks(order)
        key = uuid.uuid4()
        self.post(f"tasks/{p.pk}/report/", {"units": 100}, key)
        self.post(f"tasks/{p.pk}/report/", {"units": 100}, key)
        self.assertEqual(Report.objects.count(), 1)
        self.post(f"tasks/{p.pk}/report/", {"units": 50}, key, 400)
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        order.items.first().refresh_from_db()
        self.assertEqual(order.items.first().produced, 100)
        self.assertEqual(order.items.first().packed, 100)
        self.assertEqual(s.status(order), "producing")
        self.post(f"tasks/{k.pk}/report/", {"units": 100}, expected=400)
        self.post(f"tasks/{p.pk}/report/", {"units": 100})
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        self.assertEqual(s.status(order), "completed")
        self.assertEqual(order.shipments.count(), 2)
        self.post(f"orders/{order.pk}/issue/")
        order.refresh_from_db()
        self.assertEqual(s.status(order), "issued")
        self.post(f"tasks/{p.pk}/report/", {"units": 1}, expected=400)

    def test_flavor_grouping_and_frozen_snapshot(self):
        variant2 = Variant.objects.create(
            product=self.product, sku="KAR100", name="Karmel 100", weight_g=100
        )
        r = self.post(
            "orders/save/",
            {
                "customer_id": self.customer.pk,
                "delivery": "courier",
                "delivery_address_id": "a1",
                "due_at": timezone.now().isoformat(),
                "items": [
                    {"variant_id": self.variant.pk, "quantity": 100},
                    {"variant_id": variant2.pk, "quantity": 20},
                ],
                "confirm": True,
            },
        )
        order = Order.objects.get(pk=r.data["id"])
        self.assertEqual(order.tasks.filter(kind="production").count(), 2)
        self.assertEqual(order.tasks.filter(kind="shipping").count(), 2)
        first = order.tasks.filter(kind="production").order_by("id").first()
        self.post(f"tasks/{first.pk}/report/", {"units": 100})
        self.assertEqual(s.status(order), "producing")
        self.variant.weight_g = 40
        self.variant.save()
        self.post(f"orders/{order.pk}/confirm/")
        self.assertEqual(order.items.first().weight_g, 30)
        self.assertEqual(order.tasks.count(), 4)

    def test_label_gate_version_and_download(self):
        order = self.order(custom=True)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"units": 100}, expected=400)
        lid = self.upload(p.item)
        self.post(f"labels/{lid}/approve/")
        self.post(f"tasks/{p.pk}/report/", {"units": 100})
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        report = Report.objects.get(task=p)
        self.assertEqual(report.label_id, lid)
        second = self.upload(p.item)
        self.post(f"tasks/{p.pk}/report/", {"units": 100}, expected=400)
        self.post(f"labels/{lid}/approve/", expected=400)
        self.post(f"labels/{second}/approve/")
        self.post(f"tasks/{p.pk}/report/", {"units": 100})
        response = self.client.get(f"/api/labels/{lid}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        self.client.logout()
        self.assertEqual(
            self.client.get(f"/api/labels/{lid}/download/").status_code, 403
        )

    def test_cannot_ship_more_packages_than_produced(self):
        order = self.order()
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"units": 100})
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        self.post(f"tasks/{k.pk}/report/", {"units": 1}, expected=400)
        self.post(f"orders/{order.pk}/replenish/", expected=400)
        self.assertEqual(order.tasks.filter(supplemental=True).count(), 0)
        self.assertEqual(order.items.first().produced, 100)
        self.assertEqual(order.items.first().packed, 100)

    def test_overpacking_and_invalid_units(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{k.pk}/report/", {"units": 1}, expected=400)
        self.post(f"tasks/{p.pk}/report/", {"units": 10})
        self.post(f"tasks/{k.pk}/report/", {"units": 11}, expected=400)
        self.post(f"tasks/{k.pk}/report/", {"units": 1.5}, expected=400)
        self.post(f"tasks/{p.pk}/report/", {"units": "NaN"}, expected=400)
        self.post(f"tasks/{k.pk}/report/", {"units": 4})
        item = order.items.first()
        item.refresh_from_db()
        self.assertEqual(item.produced, 10)
        self.assertEqual(item.packed, 4)

    def test_hold_cancel_and_audit(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/start/")
        self.post(f"tasks/{p.pk}/report/", {"units": 5})
        self.post(f"orders/{order.pk}/hold/", {"reason": "Brak surowca"})
        self.assertFalse(WorkSession.objects.filter(ended_at=None).exists())
        self.post(f"tasks/{p.pk}/report/", {"units": 5}, expected=400)
        self.post(f"orders/{order.pk}/resume/")
        self.post(f"orders/{order.pk}/cancel/", {"reason": "Rezygnacja klienta"})
        self.assertEqual(order.items.first().produced, 5)
        self.post(f"tasks/{p.pk}/report/", {"units": 5}, expected=400)
        self.assertTrue(order.events.filter(action="Anulowano zamówienie").exists())

    def test_corrections_preserve_reports_and_packages(self):
        order = self.order(10)
        p, k = self.tasks(order)
        r = self.post(f"tasks/{p.pk}/report/", {"units": 10}).data["id"]
        packed = self.post(f"tasks/{k.pk}/report/", {"units": 10}).data["id"]
        self.post(f"reports/{r}/correct/", {"reason": "Błąd"}, expected=400)
        self.post(f"reports/{packed}/correct/", {"reason": "Błędne kliknięcie"})
        item = order.items.first()
        item.refresh_from_db()
        self.assertEqual(item.produced, 10)
        self.assertEqual(item.packed, 0)
        self.post(f"reports/{r}/correct/", {"reason": "Błędny zapis"})
        item.refresh_from_db()
        self.assertEqual(item.produced, 0)
        self.assertEqual(Report.objects.count(), 2)
        self.assertEqual(Correction.objects.count(), 2)
        self.post(f"reports/{r}/correct/", {"reason": "Jeszcze raz"}, expected=400)

    def test_shipment_correction_keeps_produced_packages(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"units": 10})
        r = self.post(f"tasks/{k.pk}/report/", {"units": 10}).data["id"]
        self.post(f"reports/{r}/correct/", {"reason": "Zła przesyłka"})
        item = order.items.first()
        item.refresh_from_db()
        self.assertEqual(item.produced, 10)
        self.assertEqual(item.packed, 0)

    def test_amend_conflict_and_completed_reopen(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"units": 10})
        self.post(f"tasks/{k.pk}/report/", {"units": 10})
        order.refresh_from_db()
        item = order.items.first()
        data = {
            "version": order.version,
            "reason": "Dodatkowe sztuki",
            "items": [{"id": item.pk, "quantity": 20}],
        }
        self.post(f"orders/{order.pk}/amend/", data)
        self.post(f"orders/{order.pk}/amend/", data, expected=400)
        item.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(item.quantity, 20)
        self.assertEqual(item.produced, 10)
        self.assertEqual(s.status(order), "producing")
        self.assertIsNone(order.completed_at)

    def test_transfer_preserves_origin_and_ledger(self):
        from decimal import Decimal

        source = self.order(10)
        p, _ = self.tasks(source)
        target = self.order(10)
        batch = Batch.objects.create(
            origin=p, order=source, product=self.product, available_g=0
        )
        s.movement(batch, source, self.admin, Decimal("400"), "Stan historyczny")
        self.post(
            f"batches/{batch.pk}/move/",
            {"order_id": target.pk, "reason": "Zmiana przydziału"},
        )
        batch.refresh_from_db()
        self.assertEqual(batch.order, target)
        self.assertEqual(batch.origin.order, source)
        self.assertEqual(s.available(target, self.product.pk), 400)
        self.assertEqual(
            sum(m.delta_g for m in batch.movements.all()), batch.available_g
        )

    def test_roles_and_private_fields(self):
        order = self.order(10)
        worker = get_user_model().objects.create_user(
            "worker", password="Test-password-123!"
        )
        worker.groups.add(Group.objects.create(name="production"))
        self.client.force_login(worker)
        self.post("orders/save/", {}, expected=403)
        self.post("catalog/products/", {"name": "Test", "code": "TEST"}, expected=403)
        data = self.client.get("/api/state/").json()
        self.assertEqual(data["orders"], [])
        self.assertEqual(data["customers"], [])
        self.assertNotIn("private@example.com", str(data))
        p, k = self.tasks(order)
        self.post(f"tasks/{k.pk}/report/", {"units": 1}, expected=403)
        self.assertEqual(self.client.get(f"/api/orders/{order.pk}/").status_code, 403)

    def test_login_and_authenticated_writes_require_csrf(self):
        c = APIClient(enforce_csrf_checks=True)
        r = c.post(
            "/api/auth/login/",
            {"username": "admin", "password": "Test-password-123!"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)
        c.get("/api/auth/me/")
        token = c.cookies["csrftoken"].value
        r = c.post(
            "/api/auth/login/",
            {"username": "admin", "password": "Test-password-123!"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(r.status_code, 200, r.content)
        r = c.post(
            "/api/orders/save/",
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 403)

    def test_bad_file_rejected(self):
        order = self.order()
        upload = io.BytesIO(b"<html>bad</html>")
        upload.name = "fake.pdf"
        r = self.client.post(
            f"/api/items/{order.items.first().pk}/labels/",
            {"file": upload},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Label.objects.exists())

    def test_active_customer_addresses_and_order_snapshot(self):
        addresses = [
            {"id": "shop1", "name": "Sklep 1", "address": "Poznań, ul. Testowa 1"},
            {"id": "shop2", "name": "Sklep 2", "address": "Gorzów, ul. Testowa 2"},
        ]
        cid = self.post(
            "catalog/customers/",
            {"name": "Sieć sklepów", "active": False, "delivery_addresses": addresses},
        ).data["id"]
        customer = Customer.objects.get(pk=cid)
        self.assertTrue(customer.active)
        data = {
            "customer_id": cid,
            "delivery": "courier",
            "delivery_address_id": "shop2",
            "due_at": timezone.now().isoformat(),
            "confirm": True,
            "items": [{"variant_id": self.variant.pk, "quantity": 10}],
        }
        oid = self.post("orders/save/", data).data["id"]
        self.assertEqual(
            Order.objects.get(pk=oid).address, "Sklep 2\nGorzów, ul. Testowa 2"
        )
        self.post("catalog/customers/", {"id": cid, "delivery_addresses": []})
        self.assertIn("Gorzów", Order.objects.get(pk=oid).address)
        self.post("orders/save/", data, expected=400)
        self.post("catalog/customers/", {"id": cid, "active": False})
        customer.refresh_from_db()
        self.assertFalse(customer.active)

    def test_inline_label_upload_is_atomic_and_idempotent(self):
        self.variant.custom_label = True
        self.variant.save()
        payload = {
            "customer_id": self.customer.pk,
            "delivery": "courier",
            "delivery_address_id": "a1",
            "due_at": timezone.now().isoformat(),
            "confirm": True,
            "items": [{"variant_id": self.variant.pk, "quantity": 10}],
        }
        key = str(uuid.uuid4())

        def upload(valid=True):
            file = io.BytesIO()
            if valid:
                Image.new("RGB", (2, 2)).save(file, format="PNG")
            else:
                file.write(b"not an image")
            file.seek(0)
            file.name = "logo.png"
            return self.client.post(
                "/api/orders/save/",
                {"payload": json.dumps(payload), "label_0": file},
                format="multipart",
                HTTP_IDEMPOTENCY_KEY=key,
            )

        self.assertEqual(upload(False).status_code, 400)
        self.assertFalse(Order.objects.exists())
        result = upload()
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(upload().data, result.data)
        self.assertEqual(Order.objects.count(), 1)
        label = Label.objects.get()
        self.assertIsNone(label.approved_at)
        self.assertTrue(label.item.custom_label)

    def test_ship_sends_the_whole_order(self):
        from .models import ShipmentLine

        self.customer.phone = "500600700"
        self.customer.save()
        other = Variant.objects.create(
            product=self.product, sku="KAR100B", name="Słony karmel", weight_g=30
        )
        response = self.post(
            "orders/save/",
            {
                "customer_id": self.customer.pk,
                "delivery": "courier",
                "delivery_address_id": "a1",
                "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
                "items": [
                    {"variant_id": self.variant.pk, "quantity": 10},
                    {"variant_id": other.pk, "quantity": 4},
                ],
                "confirm": True,
            },
        )
        order = Order.objects.get(pk=response.data["id"])
        state = self.client.get("/api/state/").json()
        card = next(
            task
            for task in state["tasks"]
            if task["kind"] == "shipping" and task["order_id"] == order.pk
        )
        self.assertEqual(len(card["items"]), 2)
        self.assertEqual(card["customer_email"], "private@example.com")
        self.assertEqual(card["customer_phone"], "500600700")
        self.assertIn("Testowa 1", card["address"])
        self.post(f"orders/{order.pk}/ship/", expected=400)
        for task in order.tasks.filter(kind="production"):
            self.post(f"tasks/{task.pk}/report/", {"units": task.item.quantity})
        self.post(f"orders/{order.pk}/ship/")
        order.refresh_from_db()
        self.assertEqual(s.status(order), "completed")
        self.assertEqual(order.shipments.count(), 1)
        self.assertEqual(ShipmentLine.objects.filter(shipment__order=order).count(), 2)
        self.post(f"orders/{order.pk}/ship/", expected=400)
        fresh = self.order(2)
        for task in fresh.tasks.filter(kind="production"):
            self.post(f"tasks/{task.pk}/report/", {"units": 2})
        worker = get_user_model().objects.create_user(
            "ship-worker", password="Test-password-123!"
        )
        worker.groups.add(Group.objects.get_or_create(name="production")[0])
        self.client.force_login(worker)
        self.post(f"orders/{fresh.pk}/ship/", expected=403)
        worker.groups.add(Group.objects.get_or_create(name="packing")[0])
        self.client.force_login(worker)
        self.assertEqual(self.client.get(f"/api/orders/{fresh.pk}/").status_code, 200)
        self.post(f"orders/{fresh.pk}/ship/")
        fresh.refresh_from_db()
        self.assertEqual(s.status(fresh), "completed")

    def test_locker_needs_a_saved_point_and_courier_is_the_default(self):
        payload = {
            "customer_id": self.customer.pk,
            "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "items": [{"variant_id": self.variant.pk, "quantity": 2}],
            "delivery": "locker",
            "confirm": False,
        }
        self.post("orders/save/", payload, expected=400)
        payload["delivery_address_id"] = "a1"
        saved = self.post("orders/save/", payload)
        order = Order.objects.get(pk=saved.data["id"])
        self.assertEqual(order.delivery, "locker")
        self.assertIn("Testowa 1", order.address)
        created = Order.objects.create(created_by=self.admin)
        self.assertEqual(created.delivery, "courier")

    def test_shipping_finishes_pickup_and_courier(self):
        order = self.order(10, pickup=True)
        self.assertFalse(order.tasks.filter(kind="packing").exists())
        self.assertTrue(order.tasks.filter(kind="shipping").exists())
        production = order.tasks.get(kind="production")
        self.post(f"tasks/{production.pk}/report/", {"units": 4})
        self.assertEqual(s.status(order), "producing")
        self.post(f"tasks/{production.pk}/report/", {"units": 6})
        self.assertEqual(s.status(order), "awaiting_shipment")
        shipping = order.tasks.get(kind="shipping")
        self.post(f"tasks/{shipping.pk}/report/", {"units": 10})
        self.assertEqual(s.status(order), "completed")
        self.assertEqual(order.shipments.count(), 1)

    def test_one_order_cannot_ship_another_orders_packages(self):
        first = self.order(10)
        second = self.order(10)
        p1, k1 = self.tasks(first)
        _, k2 = self.tasks(second)
        self.post(f"tasks/{p1.pk}/report/", {"units": 10})
        self.post(f"tasks/{k2.pk}/report/", {"units": 1}, expected=400)
        self.post(f"tasks/{k1.pk}/report/", {"units": 10})
        self.assertEqual(first.items.first().packed, 10)
        self.assertEqual(second.items.first().packed, 0)
        self.assertEqual(second.items.first().produced, 0)

    def test_existing_data_migration_preserves_mass_and_addresses(self):
        from importlib import import_module
        from django.apps import apps
        from .models import Movement

        self.customer.address = "Adres firmy"
        self.customer.save()
        order = self.order(10)
        order.address = "Stary adres sklepu"
        order.save()
        task, _ = self.tasks(order)
        batch = Batch.objects.create(
            origin=task, order=order, product=self.product, available_g=500
        )
        Movement.objects.create(
            batch=batch, order=order, user=self.admin, delta_g=500, reason="Stary stan"
        )
        import_module(
            "core.migrations.0003_existing_addresses_and_surplus"
        ).migrate_data(apps, None)
        self.customer.refresh_from_db()
        order.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(batch.available_g, 300)
        self.assertEqual(Batch.objects.get(order=None).available_g, 200)
        self.assertEqual(len(self.customer.delivery_addresses), 2)
        self.assertEqual(order.address, "Stary adres sklepu")
        self.assertTrue(order.delivery_address_id)
        for b in Batch.objects.all():
            self.assertEqual(sum(m.delta_g for m in b.movements.all()), b.available_g)


    def test_warehouse_shows_materials_and_follows_packages(self):
        from decimal import Decimal
        from .models import StockItem

        self.assertTrue(StockItem.objects.filter(code="CUKIER").exists())
        self.assertTrue(StockItem.objects.filter(code="MASLO").exists())
        self.assertTrue(StockItem.objects.filter(code="SOL").exists())
        self.assertTrue(StockItem.objects.filter(code="SYROP").exists())
        self.assertTrue(StockItem.objects.filter(code="OPAK-15").exists())
        self.assertTrue(StockItem.objects.filter(code="ETY-30-PRZOD").exists())
        self.assertTrue(StockItem.objects.filter(code="ETY-400-TYL").exists())
        order = self.order(10)
        production, packing = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 4})
        stock = StockItem.objects.get(variant=self.variant, group="popcorn")
        self.assertEqual(stock.quantity, 4)
        self.post(f"tasks/{packing.pk}/report/", {"units": 3})
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, 1)
        sugar = StockItem.objects.get(code="CUKIER")
        self.post(f"stock/{sugar.pk}/", {"quantity": "2.500", "reason": "Dostawa"})
        sugar.refresh_from_db()
        self.assertEqual(sugar.quantity, Decimal("2.500"))
        worker = get_user_model().objects.create_user(
            "stock-worker", password="Test-password-123!"
        )
        worker.groups.add(Group.objects.get_or_create(name="production")[0])
        self.client.force_login(worker)
        self.post(
            f"stock/{sugar.pk}/",
            {"quantity": "9", "reason": "Bez uprawnień"},
            expected=403,
        )
        data = self.client.get("/api/state/").json()
        self.assertTrue(any(item["code"] == "ETY-15-TYL" for item in data["stock"]))
        self.assertTrue(any(item["name"] == "Półprodukty" for item in data["categories"]))

    def test_warehouse_allocates_stock_and_accepts_deliveries(self):
        from decimal import Decimal
        from .models import StockCategory, StockItem

        s.sync_catalog_stock()
        stock = StockItem.objects.get(variant=self.variant)
        self.post(
            f"stock/{stock.pk}/",
            {"quantity": "7", "reason": "Stan początkowy"},
        )
        order = self.order(10)
        item = order.items.get()
        self.assertEqual(item.allocated, 7)
        production, shipping = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 4}, expected=400)
        self.post(f"tasks/{production.pk}/report/", {"units": 3})
        stock.refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(stock.reserved, Decimal("10"))
        second = self.order(5)
        self.assertEqual(second.items.get().allocated, 0)
        self.post(f"orders/{order.pk}/cancel/", {"reason": "Rezygnacja"})
        stock.refresh_from_db()
        second.items.get().refresh_from_db()
        self.assertEqual(stock.quantity, Decimal("10"))
        self.assertEqual(second.items.get().allocated, 5)
        self.assertEqual(stock.reserved, Decimal("5"))
        category = self.post("stock/categories/", {"name": "Dodatki"}).data["id"]
        self.assertFalse(StockCategory.objects.get(pk=category).system)
        product = self.post(
            "stock/products/",
            {"category_id": category, "name": "Folia", "unit": "szt"},
        ).data["id"]
        self.post(
            "stock/receipt/",
            {"stock_id": product, "quantity": "12", "reason": "Dostawa z poniedziałku"},
        )
        self.assertEqual(StockItem.objects.get(pk=product).quantity, Decimal("12"))
        sugar = StockItem.objects.get(code="CUKIER")
        self.post(
            "stock/receipt/",
            {"stock_id": sugar.pk, "quantity": "1.5", "reason": "Worek cukru"},
        )
        sugar.refresh_from_db()
        self.assertEqual(sugar.quantity, Decimal("1.5"))
        self.post(f"tasks/{shipping.pk}/report/", {"units": 1}, expected=400)
        worker = get_user_model().objects.create_user(
            "receipt-worker", password="Test-password-123!"
        )
        worker.groups.add(Group.objects.get_or_create(name="production")[0])
        self.client.force_login(worker)
        self.post(
            "stock/receipt/",
            {"stock_id": sugar.pk, "quantity": "1", "reason": "Bez uprawnień"},
            expected=403,
        )

    def test_recipe_consumes_material_and_remembers_supplier(self):
        from decimal import Decimal
        from .models import Recipe, StockItem

        sugar = StockItem.objects.get(code="CUKIER")
        self.post(
            f"stock/{sugar.pk}/",
            {"quantity": "1.000", "reason": "Stan początkowy cukru"},
        )
        supplier = self.post(
            "suppliers/",
            {"name": "Cukrownia", "phone": "500100200", "email": "biuro@cukrownia.test"},
        ).data["id"]
        self.post(f"stock/{sugar.pk}/supplier/", {"supplier_id": supplier})
        sugar.refresh_from_db()
        self.assertEqual(sugar.supplier.name, "Cukrownia")
        self.post(
            "recipes/",
            {
                "variant_id": self.variant.pk,
                "lines": [{"stock_id": sugar.pk, "quantity": "0.020"}],
            },
        )
        order = self.order(10)
        production, _ = self.tasks(order)
        report = self.post(f"tasks/{production.pk}/report/", {"units": 10}).data["id"]
        sugar.refresh_from_db()
        self.assertEqual(sugar.quantity, Decimal("0.800"))
        second = self.order(50)
        production_two, _ = self.tasks(second)
        self.post(f"tasks/{production_two.pk}/report/", {"units": 50}, expected=400)
        sugar.refresh_from_db()
        self.assertEqual(sugar.quantity, Decimal("0.800"))
        self.post(f"reports/{report}/correct/", {"reason": "Cofnięcie produkcji"})
        sugar.refresh_from_db()
        self.assertEqual(sugar.quantity, Decimal("1.000"))
        popcorn = StockItem.objects.get(variant=self.variant)
        self.post(
            "recipes/",
            {
                "variant_id": self.variant.pk,
                "lines": [{"stock_id": popcorn.pk, "quantity": "1"}],
            },
            expected=400,
        )
        self.post("recipes/", {"variant_id": self.variant.pk, "lines": []})
        self.assertFalse(Recipe.objects.filter(variant=self.variant).exists())
        worker = get_user_model().objects.create_user(
            "recipe-worker", password="Test-password-123!"
        )
        worker.groups.add(Group.objects.get_or_create(name="production")[0])
        self.client.force_login(worker)
        self.post(
            "recipes/",
            {
                "variant_id": self.variant.pk,
                "lines": [{"stock_id": sugar.pk, "quantity": "0.010"}],
            },
            expected=403,
        )


    def test_full_stock_coverage_needs_no_production(self):
        from .models import StockItem
        s.sync_catalog_stock()
        stock = StockItem.objects.get(variant=self.variant)
        self.post(f"stock/{stock.pk}/", {"quantity": "10", "reason": "Initial"})
        order = self.order(10)
        self.assertEqual(order.items.get().allocated, 10)
        self.assertFalse(order.tasks.filter(kind="production").exists())
        self.post(f"orders/{order.pk}/ship/")
        stock.refresh_from_db()
        self.assertEqual((stock.quantity, stock.reserved), (0, 0))

    def test_failed_recipe_report_rolls_back_all_stock_and_can_retry(self):
        from decimal import Decimal
        from .models import StockItem, StockMove
        s.sync_catalog_stock()
        sugar = StockItem.objects.get(code="CUKIER")
        self.post(f"stock/{sugar.pk}/", {"quantity": "0.1", "reason": "Initial"})
        self.post("recipes/", {"variant_id": self.variant.pk,
                  "lines": [{"stock_id": sugar.pk, "quantity": "0.020"}]})
        order = self.order(10)
        task, _ = self.tasks(order)
        moves = StockMove.objects.count()
        key = uuid.uuid4()
        self.post(f"tasks/{task.pk}/report/", {"units": 10}, key, expected=400)
        self.assertFalse(Report.objects.filter(task=task).exists())
        self.assertEqual(order.items.get().produced, 0)
        self.assertEqual(StockMove.objects.count(), moves)
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (0, 0))
        self.assertEqual(StockItem.objects.get(pk=sugar.pk).quantity, Decimal("0.100"))
        self.post("stock/receipt/", {"stock_id": sugar.pk, "quantity": "0.1", "reason": "Delivery"})
        self.post(f"tasks/{task.pk}/report/", {"units": 10}, key)
        self.post(f"tasks/{task.pk}/report/", {"units": 10}, key)
        self.assertEqual(Report.objects.filter(task=task).count(), 1)
        self.assertEqual(StockItem.objects.get(pk=sugar.pk).quantity, 0)

    def test_repeated_shipment_does_not_remove_stock_twice(self):
        from .models import StockItem
        order = self.order(10)
        task, _ = self.tasks(order)
        self.post(f"tasks/{task.pk}/report/", {"units": 10})
        key = uuid.uuid4()
        first = self.post(f"orders/{order.pk}/ship/", key=key)
        second = self.post(f"orders/{order.pk}/ship/", key=key)
        self.assertEqual(first.data, second.data)
        self.assertEqual(order.shipments.count(), 1)
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (0, 0))

    def test_reserved_stock_cannot_be_removed_by_manual_adjustment(self):
        from .models import StockItem
        s.sync_catalog_stock()
        stock = StockItem.objects.get(variant=self.variant)
        self.post(f"stock/{stock.pk}/", {"quantity": "10", "reason": "Initial"})
        self.order(8)
        self.post(f"stock/{stock.pk}/", {"quantity": "7", "reason": "Count"}, expected=400)
        stock.refresh_from_db()
        self.assertEqual((stock.quantity, stock.reserved), (10, 8))

    def test_cancelled_custom_label_stock_is_not_allocated_to_another_customer(self):
        # Regression: finished packs carrying customer A's artwork must not
        # satisfy customer B's order merely because the generic SKU matches.
        first = self.order(10, custom=True)
        production, _ = self.tasks(first)
        label_id = self.upload(production.item)
        self.post(f"labels/{label_id}/approve/")
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        self.post(f"orders/{first.pk}/cancel/", {"reason": "Customer cancelled"})
        self.customer = Customer.objects.create(
            name="Different customer",
            delivery_addresses=[{"id": "a1", "name": "Office", "address": "Other street 2"}],
        )
        second = self.order(5, custom=True)
        self.assertEqual(second.items.get().allocated, 0,
                         "Stock bearing another customer's logo must not be allocated")
        self.assertTrue(second.tasks.filter(kind="production").exists())

    def test_matching_artwork_version_can_be_reserved_again(self):
        from .models import StockItem

        first = self.order(10, custom=True)
        production, _ = self.tasks(first)
        self.post(f"labels/{self.upload(production.item)}/approve/")
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        plain = StockItem.objects.filter(
            variant=self.variant, artwork_sha256="", artwork_unknown=False
        ).first()
        self.assertTrue(plain is None or plain.quantity == 0)
        self.post(f"orders/{first.pk}/cancel/", {"reason": "Customer cancelled"})
        second = self.order(4, custom=True)
        self.assertEqual(second.items.get().allocated, 0)
        label_id = self.upload(second.items.get(), "red")
        self.post(f"labels/{label_id}/approve/")
        self.assertEqual(second.items.get().allocated, 4)
        lot = StockItem.objects.get(artwork_sha256__gt="", artwork_unknown=False)
        self.assertEqual((lot.quantity, lot.reserved), (10, 4))

    def test_new_label_version_does_not_take_older_packs(self):
        from .models import StockItem

        first = self.order(10, custom=True)
        production, _ = self.tasks(first)
        self.post(f"labels/{self.upload(production.item, 'red')}/approve/")
        self.post(f"tasks/{production.pk}/report/", {"units": 6})
        self.post(f"labels/{self.upload(production.item, 'blue')}/approve/")
        self.post(f"tasks/{production.pk}/report/", {"units": 4})
        self.assertEqual(
            StockItem.objects.filter(variant=self.variant).exclude(artwork_sha256="").count(),
            2,
        )
        self.post(f"orders/{first.pk}/cancel/", {"reason": "Split versions"})
        second = self.order(10, custom=True)
        self.post(f"labels/{self.upload(second.items.get(), 'red')}/approve/")
        self.assertEqual(second.items.get().allocated, 6)
        blue_v1 = self.order(4, custom=True)
        self.post(f"labels/{self.upload(blue_v1.items.get(), 'blue')}/approve/")
        self.assertEqual(blue_v1.items.get().allocated, 0)
        blue_v2 = self.order(4, custom=True)
        item = blue_v2.items.get()
        self.post(f"labels/{self.upload(item, 'green')}/approve/")
        self.assertEqual(blue_v2.items.get().allocated, 0)
        self.post(f"labels/{self.upload(item, 'blue')}/approve/")
        self.assertEqual(blue_v2.items.get().allocated, 4)

    def test_new_artwork_does_not_ship_previously_reserved_packs(self):
        from .models import Report, StockItem

        first = self.order(10, custom=True)
        production, _ = self.tasks(first)
        self.post(f"labels/{self.upload(production.item, 'red')}/approve/")
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        self.post(f"orders/{first.pk}/cancel/", {"reason": "Customer cancelled"})
        second = self.order(5, custom=True)
        red = self.upload(second.items.get(), "red")
        self.post(f"labels/{red}/approve/")
        self.assertEqual(second.items.get().allocated, 5)
        blue = self.upload(second.items.get(), "blue")
        self.post(f"labels/{blue}/approve/")
        self.assertEqual(second.items.get().allocated, 5)
        red_lot = StockItem.objects.get(artwork_version=1, artwork_unknown=False)
        self.assertEqual((red_lot.quantity, red_lot.reserved), (10, 5))
        blocked = self.post(f"orders/{second.pk}/ship/", expected=400)
        self.assertIn("grafik", blocked.content.decode().lower())
        red_lot.refresh_from_db()
        self.assertEqual((red_lot.quantity, red_lot.reserved), (10, 5))
        self.post(f"labels/{blue}/approve/", {"settle_previous": True})
        item = second.items.get()
        self.assertEqual((item.allocated, item.produced), (0, 0))
        red_lot.refresh_from_db()
        self.assertEqual((red_lot.quantity, red_lot.reserved), (10, 0))
        self.post(f"orders/{second.pk}/ship/", expected=400)
        task = second.tasks.get(kind="production")
        self.post(f"tasks/{task.pk}/report/", {"units": 5})
        self.post(f"orders/{second.pk}/ship/")
        report = Report.objects.get(task__order=second, task__kind="shipping")
        self.assertEqual(report.label_id, blue)
        red_lot.refresh_from_db()
        self.assertEqual((red_lot.quantity, red_lot.reserved), (10, 0))
        blue_lot = StockItem.objects.get(artwork_version=2)
        self.assertEqual((blue_lot.quantity, blue_lot.reserved), (0, 0))

    def test_unknown_artwork_stock_is_not_allocated(self):
        from .models import StockItem

        s.sync_catalog_stock(self.variant)
        plain = StockItem.objects.get(variant=self.variant, artwork_sha256="")
        StockItem.objects.create(
            code="UNK-LEGACY",
            name="Karmel 30 · grafika nieznana",
            group="popcorn",
            unit="szt",
            quantity=8,
            variant=self.variant,
            artwork_unknown=True,
            category=plain.category,
        )
        order = self.order(5, custom=True)
        self.post(f"labels/{self.upload(order.items.get())}/approve/")
        self.assertEqual(order.items.get().allocated, 0)
        legacy = StockItem.objects.get(code="UNK-LEGACY")
        self.assertEqual((legacy.quantity, legacy.reserved), (8, 0))

    def test_logo_correction_and_receipt_keep_the_same_lot(self):
        from .models import StockItem

        order = self.order(6, custom=True)
        production, shipping = self.tasks(order)
        self.post(f"labels/{self.upload(production.item, 'red')}/approve/")
        report = self.post(f"tasks/{production.pk}/report/", {"units": 6}).data["id"]
        lot = StockItem.objects.get(artwork_sha256__gt="")
        self.post(f"reports/{report}/correct/", {"reason": "Zły zapis"})
        lot.refresh_from_db()
        self.assertEqual((lot.quantity, lot.reserved), (0, 0))
        self.post(f"tasks/{production.pk}/report/", {"units": 6})
        self.post(f"stock/receipt/", {"stock_id": lot.pk, "quantity": "2", "reason": "Zwrot"})
        lot.refresh_from_db()
        self.assertEqual((lot.quantity, lot.reserved), (8, 6))
        other = self.order(3, custom=True)
        self.post(f"labels/{self.upload(other.items.get(), 'red')}/approve/")
        self.assertEqual(other.items.get().allocated, 2)
        shipped = self.post(f"tasks/{shipping.pk}/report/", {"units": 6}).data["id"]
        self.post(f"reports/{shipped}/correct/", {"reason": "Cofnij wysyłkę"})
        lot.refresh_from_db()
        self.assertEqual(lot.quantity, 8)

    def test_reading_state_does_not_write_business_rows(self):
        from django.test.utils import CaptureQueriesContext
        from .models import StockItem

        s.sync_catalog_stock()
        extra = Variant.objects.create(
            product=self.product, sku="NO-SYNC", name="Bez synchronizacji", weight_g=30
        )
        before = list(StockItem.objects.order_by("pk").values_list("pk", "quantity", "reserved", "name"))
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/api/state/")
            detail = self.client.get(f"/api/stock/{StockItem.objects.get(code='CUKIER').pk}/detail/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(StockItem.objects.filter(variant=extra).exists())
        self.assertEqual(
            before,
            list(StockItem.objects.order_by("pk").values_list("pk", "quantity", "reserved", "name")),
        )
        writes = [
            query["sql"]
            for query in ctx.captured_queries
            if query["sql"].lstrip()[:6].upper() in {"INSERT", "UPDATE", "DELETE"}
            and "core_" in query["sql"].lower()
        ]
        self.assertEqual(writes, [])

    def test_order_page_does_not_shrink_the_totals(self):
        self.order(5)
        self.order(6)
        self.order(7)
        response = self.client.get("/api/state/?orders_scope=page&orders_limit=1")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(len(body["orders"]), 1)
        self.assertGreaterEqual(body["summary"]["orders"], 3)
        self.assertGreaterEqual(body["summary"]["active"], 3)
        self.assertGreaterEqual(body["orders_page"]["count"], 3)
        hidden = self.client.get("/api/state/?orders_scope=none")
        self.assertEqual(hidden.json()["orders"], [])
        self.assertGreaterEqual(hidden.json()["summary"]["orders"], 3)

    def test_login_attempts_are_limited_for_every_worker(self):
        client = APIClient()
        for _ in range(10):
            response = client.post(
                "/api/auth/login/",
                {"username": "admin", "password": "wrong-password"},
                format="json",
            )
            self.assertEqual(response.status_code, 400, response.content)
        blocked = client.post(
            "/api/auth/login/",
            {"username": "admin", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 429, blocked.content)

    def test_technical_cleanup_keeps_orders_and_stock_history(self):
        from django.core.management import call_command
        from django.utils import timezone
        from datetime import timedelta
        from .models import LoginAttempt, RequestReceipt, StockMove

        order = self.order(4)
        production, _ = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 2})
        RequestReceipt.objects.update(created_at=timezone.now() - timedelta(days=8))
        LoginAttempt.objects.create(
            ident="abc", created_at=timezone.now() - timedelta(days=2)
        )
        moves = StockMove.objects.count()
        call_command("purge_technical")
        self.assertEqual(Order.objects.filter(pk=order.pk).count(), 1)
        self.assertEqual(StockMove.objects.count(), moves)
        self.assertEqual(RequestReceipt.objects.count(), 0)
        self.assertEqual(LoginAttempt.objects.count(), 0)


    # Scenario references (independent POPMES implementation):
    # ERPNext: stock/doctype/stock_reservation_entry/test_stock_reservation_entry.py
    # InvenTree: src/backend/InvenTree/build/tests.py
    def test_shipment_reversal_restores_stock_and_reservation(self):
        from .models import StockItem
        order = self.order(10)
        production, shipping = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        report = self.post(f"tasks/{shipping.pk}/report/", {"units": 10}).data["id"]
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (0, 0))
        self.post(f"reports/{report}/correct/", {"reason": "Shipment reversed"})
        stock.refresh_from_db()
        self.assertEqual((stock.quantity, stock.reserved), (10, 10))
        other = self.order(10)
        self.assertEqual(other.items.get().allocated, 0)
        self.post(f"orders/{order.pk}/ship/")
        stock.refresh_from_db()
        self.assertEqual((stock.quantity, stock.reserved), (0, 0))

    def test_second_correction_cannot_duplicate_stock(self):
        from .models import StockItem, StockMove
        order = self.order(10)
        production, shipping = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        report = self.post(f"tasks/{shipping.pk}/report/", {"units": 10}).data["id"]
        self.post(f"reports/{report}/correct/", {"reason": "First correction"})
        count = StockMove.objects.count()
        self.post(f"reports/{report}/correct/", {"reason": "Repeated correction"}, expected=400)
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (10, 10))
        self.assertEqual(StockMove.objects.count(), count)
        self.assertEqual(Correction.objects.filter(report_id=report).count(), 1)

    def test_partial_shipment_cancel_releases_only_unshipped_units(self):
        from .models import StockItem
        order = self.order(10)
        production, shipping = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        self.post(f"tasks/{shipping.pk}/report/", {"units": 4})
        self.post(f"orders/{order.pk}/cancel/", {"reason": "Cancel remainder"})
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (6, 0))
        other = self.order(8)
        self.assertEqual(other.items.get().allocated, 6)
        self.assertEqual(s.to_produce(other.items.get()), 2)
        stock.refresh_from_db()
        self.assertEqual((stock.quantity, stock.reserved), (6, 6))

    def test_cancelled_order_cannot_restart_or_ship(self):
        from .models import StockItem, StockMove
        order = self.order(10)
        production, _ = self.tasks(order)
        self.post(f"tasks/{production.pk}/report/", {"units": 10})
        self.post(f"orders/{order.pk}/cancel/", {"reason": "Cancelled"})
        count = StockMove.objects.count()
        self.post(f"tasks/{production.pk}/start/", expected=400)
        self.post(f"orders/{order.pk}/ship/", expected=400)
        self.assertFalse(order.shipments.exists())
        self.assertFalse(WorkSession.objects.filter(task=production, ended_at=None).exists())
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (10, 0))
        self.assertEqual(StockMove.objects.count(), count)

    def test_stock_of_other_weight_cannot_cover_order(self):
        from .models import StockItem
        other_variant = Variant.objects.create(
            product=self.product, sku="KAR100-OTHER", name="Karmel 100g", weight_g=100)
        s.sync_catalog_stock()
        stock = StockItem.objects.get(variant=other_variant)
        self.post(f"stock/{stock.pk}/", {"quantity": "20", "reason": "Initial"})
        order = self.order(10)
        self.assertEqual(order.items.get().allocated, 0)
        self.assertEqual(s.to_produce(order.items.get()), 10)
        stock.refresh_from_db()
        self.assertEqual((stock.quantity, stock.reserved), (20, 0))

    def test_later_ingredient_shortage_restores_earlier_ingredient(self):
        from decimal import Decimal
        from .models import StockItem, StockMove
        first = StockItem.objects.create(code="TEST-FIRST", name="First material",
                                         group="material", unit="kg", quantity="1")
        second = StockItem.objects.create(code="TEST-SECOND", name="Second material",
                                          group="material", unit="kg", quantity="0")
        self.post("recipes/", {"variant_id": self.variant.pk, "lines": [
            {"stock_id": first.pk, "quantity": "0.020"},
            {"stock_id": second.pk, "quantity": "0.010"},
        ]})
        order = self.order(10)
        production, _ = self.tasks(order)
        count = StockMove.objects.count()
        self.post(f"tasks/{production.pk}/report/", {"units": 10}, expected=400)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.quantity, Decimal("1"))
        self.assertEqual(second.quantity, 0)
        self.assertEqual(order.items.get().produced, 0)
        self.assertFalse(Report.objects.filter(task=production).exists())
        stock = StockItem.objects.get(variant=self.variant)
        self.assertEqual((stock.quantity, stock.reserved), (0, 0))
        self.assertEqual(StockMove.objects.count(), count)

    def test_stock_detail_edits_name_supplier_and_unit(self):
        from decimal import Decimal
        from .models import StockCategory, StockItem, Supplier

        sugar = StockItem.objects.get(code="CUKIER")
        self.assertIsNotNone(sugar.category_id)
        supplier_id = self.post(
            "suppliers/",
            {
                "name": "Młyn",
                "contact": "Anna",
                "phone": "500100200",
                "email": "biuro@mlyn.test",
            },
        ).data["id"]
        self.post(
            f"stock/{sugar.pk}/edit/",
            {
                "name": "Cukier trzcinowy",
                "category_id": sugar.category_id,
                "unit": "kg",
                "supplier_id": supplier_id,
            },
        )
        sugar.refresh_from_db()
        self.assertEqual(sugar.name, "Cukier trzcinowy")
        self.assertEqual(sugar.supplier_id, supplier_id)
        s.sync_catalog_stock()
        sugar.refresh_from_db()
        self.assertEqual(sugar.name, "Cukier trzcinowy")
        self.post(
            f"stock/{sugar.pk}/",
            {"quantity": "2.000", "reason": "Stan początkowy"},
        )
        self.post(
            f"stock/{sugar.pk}/edit/",
            {
                "name": "Cukier",
                "category_id": sugar.category_id,
                "unit": "kg",
                "supplier_id": supplier_id,
            },
        )
        sugar.refresh_from_db()
        self.assertEqual(sugar.name, "Cukier")
        self.assertEqual(sugar.quantity, Decimal("2.000"))
        self.post(
            f"stock/{sugar.pk}/edit/",
            {
                "name": "Cukier",
                "category_id": sugar.category_id,
                "unit": "szt",
                "supplier_id": supplier_id,
            },
            expected=400,
        )
        sugar.refresh_from_db()
        self.assertEqual(sugar.unit, "kg")
        finished = StockCategory.objects.get(system=True)
        self.post(
            f"stock/{sugar.pk}/edit/",
            {
                "name": "Cukier",
                "category_id": finished.pk,
                "unit": "kg",
                "supplier_id": supplier_id,
            },
            expected=400,
        )
        detail = self.client.get(f"/api/stock/{sugar.pk}/detail/")
        self.assertEqual(detail.status_code, 200, detail.content)
        self.assertEqual(detail.data["supplier"]["phone"], "500100200")
        self.assertEqual(detail.data["variant"], None)
        self.assertTrue(detail.data["moves"])
        popcorn = StockItem.objects.get(variant=self.variant)
        self.post(
            f"stock/{popcorn.pk}/edit/",
            {
                "name": "Inna nazwa",
                "category_id": sugar.category_id,
                "unit": "szt",
            },
            expected=400,
        )
        profile = self.client.get(f"/api/stock/{popcorn.pk}/detail/")
        self.assertEqual(profile.status_code, 200, profile.content)
        self.assertEqual(profile.data["variant"]["sku"], self.variant.sku)
        category_id = self.post("stock/categories/", {"name": "Przyprawy"}).data["id"]
        item_id = self.post(
            "stock/products/",
            {"category_id": category_id, "name": "Cynamon", "unit": "kg"},
        ).data["id"]
        self.post(
            f"stock/{item_id}/edit/",
            {
                "name": "Cynamon mielony",
                "category_id": category_id,
                "unit": "szt",
                "supplier_id": None,
            },
        )
        item = StockItem.objects.get(pk=item_id)
        self.assertEqual(item.name, "Cynamon mielony")
        self.assertEqual(item.unit, "szt")
        self.assertIsNone(item.supplier_id)
        self.post(
            f"suppliers/{supplier_id}/",
            {"name": "Młyn nowy", "contact": "Jan", "email": "", "phone": "600"},
        )
        self.assertEqual(Supplier.objects.get(pk=supplier_id).phone, "600")
        other = self.post(
            "suppliers/",
            {"name": "Drugi młyn", "contact": "", "email": "", "phone": ""},
        ).data["id"]
        self.post(
            f"suppliers/{supplier_id}/",
            {"name": "Drugi młyn", "contact": "", "email": "", "phone": ""},
            expected=400,
        )
        self.assertNotEqual(Supplier.objects.get(pk=other).pk, supplier_id)
        worker = get_user_model().objects.create_user(
            "detail-worker", password="Test-password-123!"
        )
        worker.groups.add(Group.objects.get_or_create(name="production")[0])
        self.client.force_login(worker)
        seen = self.client.get(f"/api/stock/{sugar.pk}/detail/")
        self.assertEqual(seen.status_code, 200, seen.content)
        self.post(
            f"stock/{sugar.pk}/edit/",
            {
                "name": "X",
                "category_id": sugar.category_id,
                "unit": "kg",
            },
            expected=403,
        )

    def test_account_settings_and_password(self):
        saved = self.post(
            "account/",
            {
                "name": "Filip Kosznik",
                "email": "filip@example.com",
                "phone": "500 100 200",
                "street": "ul. Słoneczna 14",
                "postal_code": "61-001",
                "city": "Poznań",
                "country": "Polska",
                "language": "en",
                "timezone": "Europe/Berlin",
                "start_page": "orders",
                "appearance": "dark",
            },
        )
        self.assertEqual(saved.data["city"], "Poznań")
        self.assertEqual(saved.data["language"], "en")
        self.assertEqual(saved.data["appearance"], "dark")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.first_name, "Filip Kosznik")
        self.assertEqual(self.admin.email, "filip@example.com")
        self.assertEqual(self.admin.profile.timezone, "Europe/Berlin")
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.data["user"]["street"], "ul. Słoneczna 14")
        self.post(
            "account/",
            {
                "name": "Filip",
                "email": "nie-email",
                "language": "pl",
                "timezone": "Europe/Warsaw",
                "start_page": "dashboard",
                "appearance": "dark",
            },
            expected=400,
        )
        self.post(
            "account/",
            {
                "name": "Filip",
                "email": "filip@example.com",
                "language": "pl",
                "timezone": "Europe/Warsaw",
                "start_page": "dashboard",
                "appearance": "blue",
            },
            expected=400,
        )
        self.post(
            "account/password/",
            {
                "current_password": "zle-haslo",
                "password": "New-password-123!",
                "password_repeat": "New-password-123!",
            },
            expected=400,
        )
        self.post(
            "account/password/",
            {
                "current_password": "Test-password-123!",
                "password": "New-password-123!",
                "password_repeat": "inne-haslo-123!",
            },
            expected=400,
        )
        self.post(
            "account/password/",
            {
                "current_password": "Test-password-123!",
                "password": "New-password-123!",
                "password_repeat": "New-password-123!",
            },
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("New-password-123!"))
        me = self.client.get("/api/auth/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["user"]["name"], "Filip Kosznik")

    def test_admin_settings_workspaces_and_users(self):
        sales = get_user_model().objects.create_user(
            "sales-settings", password="Test-password-123!"
        )
        sales.groups.add(Group.objects.get_or_create(name="sales")[0])
        self.client.force_login(sales)
        self.post(
            "organization/",
            {"name": "Inna", "default_language": "pl", "theme": "plum"},
            expected=403,
        )
        self.client.force_login(self.admin)
        home = self.client.get("/api/state/")
        self.assertEqual(home.data["organization"]["name"], "POPME")
        self.assertEqual(home.data["organization"]["theme"], "plum")
        self.assertEqual(len(home.data["workspaces"]), 1)
        self.assertTrue(home.data["workspaces"][0]["primary"])
        saved = self.post(
            "organization/",
            {
                "name": "Popcornownia",
                "default_language": "en",
                "theme": "teal",
            },
        )
        self.assertEqual(saved.data["name"], "Popcornownia")
        self.post("organization/", {"name": "  ", "default_language": "pl", "theme": "plum"}, expected=400)
        self.post(
            "organization/",
            {"name": "Popcornownia", "default_language": "xx", "theme": "teal"},
            expected=400,
        )
        created = self.post("workspaces/", {"name": "Hala 2"})
        self.post("workspaces/", {"name": "hala 2"}, expected=400)
        primary = next(item for item in home.data["workspaces"] if item["primary"])
        self.post(
            "workspaces/",
            {"id": primary["id"], "name": primary["name"], "active": False},
            expected=400,
        )
        here = self.order(quantity=2, pickup=True)
        self.assertEqual(here.workspace_id, primary["id"])
        self.post("workspaces/current/", {"id": created.data["id"]})
        away = self.client.get("/api/state/")
        self.assertEqual(away.data["workspace_id"], created.data["id"])
        self.assertNotIn(here.pk, [row["id"] for row in away.data["orders"]])
        other = self.order(quantity=2, pickup=True)
        self.assertEqual(other.workspace_id, created.data["id"])
        self.post("workspaces/current/", {"id": primary["id"]})
        back = self.client.get("/api/state/")
        visible = [row["id"] for row in back.data["orders"]]
        self.assertIn(here.pk, visible)
        self.assertNotIn(other.pk, visible)
        person = self.post(
            "users/",
            {
                "username": "hala.user",
                "name": "Hala User",
                "password": "Test-password-123!",
                "roles": ["production"],
                "active": True,
            },
        )
        account = get_user_model().objects.get(pk=person.data["id"])
        self.assertEqual(account.profile.language, "en")
        self.post(
            "users/",
            {
                "id": account.pk,
                "username": "hala.user",
                "name": "Hala User",
                "roles": ["production", "packing"],
                "active": True,
            },
        )
        account.refresh_from_db()
        self.assertEqual(set(s.roles(account)), {"production", "packing"})
        self.post(
            "workspaces/",
            {"id": created.data["id"], "name": "Hala 2", "active": False},
        )
        self.post("workspaces/current/", {"id": created.data["id"]}, expected=404)

    def test_other_workspace_cannot_read_or_replay_an_order(self):
        order = self.order(3)
        home = self.client.get("/api/state/?orders_scope=none").json()
        primary = next(item["id"] for item in home["workspaces"] if item["primary"])
        created = self.post("workspaces/", {"name": "Inna hala"})
        key = uuid.uuid4()
        self.post(f"orders/{order.pk}/hold/", {"reason": "Blokada"}, key)
        self.post("workspaces/current/", {"id": created.data["id"]})
        self.assertEqual(self.client.get(f"/api/orders/{order.pk}/").status_code, 404)
        self.post(f"orders/{order.pk}/cancel/", {"reason": "Cudze"}, expected=403)
        self.post(f"orders/{order.pk}/hold/", {"reason": "Blokada"}, key, expected=403)
        self.post("workspaces/current/", {"id": primary})
        self.assertEqual(self.client.get(f"/api/orders/{order.pk}/").status_code, 200)

    def test_proxy_clients_do_not_share_a_login_limit_and_spoofing_fails(self):
        os_limits = patch.dict(
            "os.environ", {"LOGIN_IP_LIMIT": "30", "LOGIN_ACCOUNT_LIMIT": "10"}
        )
        os_limits.start()
        self.addCleanup(os_limits.stop)

        def attempt(ip, username, remote="172.18.0.8"):
            return self.client.post(
                "/api/auth/login/",
                {"username": username, "password": "wrong-password"},
                format="json",
                REMOTE_ADDR=remote,
                HTTP_X_REAL_IP=ip,
                HTTP_X_FORWARDED_FOR="198.51.100.9",
            )

        for _ in range(10):
            self.assertEqual(attempt("203.0.113.10", "one-user").status_code, 400)
        self.assertEqual(attempt("203.0.113.10", "one-user").status_code, 429)
        self.assertEqual(attempt("203.0.113.11", "other-user").status_code, 400)
        for index in range(30):
            self.assertEqual(
                attempt(
                    f"198.51.100.{index + 1}",
                    f"person-{index}",
                    remote="8.8.8.8",
                ).status_code,
                400,
            )
        blocked = attempt("198.51.100.200", "person-extra", remote="8.8.8.8")
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("ponownie", blocked.content.decode().lower())

    def test_order_page_is_limited_in_the_database(self):
        from django.test.utils import CaptureQueriesContext

        for _ in range(3):
            self.order(2)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/api/state/?orders_scope=page&orders_limit=1&orders_sort=due&orders_dir=asc")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(len(body["orders"]), 1)
        self.assertGreaterEqual(body["summary"]["orders"], 3)
        self.assertGreaterEqual(body["orders_page"]["count"], 3)
        limited = [
            query["sql"]
            for query in ctx.captured_queries
            if " LIMIT " in query["sql"].upper()
        ]
        self.assertTrue(limited)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locks required")
class ConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        super().setUp()
        # reset_sequences rewinds identity counters while rows created by
        # migrations are still present. Advance the stock sequence past them.
        with connection.cursor() as cursor:
            for table in ("core_stockitem", "core_stockmove"):
                cursor.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE((SELECT MAX(id) FROM {table}), 1),
                        (SELECT COUNT(*) > 0 FROM {table})
                    )
                    """
                )

    def test_two_workers_cannot_consume_same_batch(self):
        a = get_user_model().objects.create_superuser("a", password="test")
        b = get_user_model().objects.create_superuser("b", password="test")
        product = Product.objects.create(code="P", name="Product")
        variant = Variant.objects.create(
            product=product, sku="P30", name="30g", weight_g=30
        )
        customer = Customer.objects.create(name="Customer")
        order = Order.objects.create(
            customer=customer,
            created_by=a,
            due_at=timezone.now(),
            delivery="courier",
            address="Kurier 1",
        )
        item = Item(order=order, variant=variant, quantity=100)
        s.snapshot_item(item, variant)
        item.save()
        with transaction.atomic():
            s.confirm(order, a)
            p = order.tasks.get(kind="production")
            s.production_report(p, a, {"units": 10})
        task = order.tasks.get(kind="shipping")
        barrier = threading.Barrier(2)

        def report(uid):
            connections.close_all()
            try:
                client = APIClient()
                client.force_login(get_user_model().objects.get(pk=uid))
                barrier.wait(timeout=10)
                response = client.post(
                    f"/api/tasks/{task.pk}/report/",
                    {"units": 10},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                )
                return response.status_code
            finally:
                # Each thread owns a persistent connection; close it before
                # Django drops the isolated test database.
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            for attempt in range(5):
                if attempt:
                    with transaction.atomic():
                        s.production_report(p, a, {"units": 10})
                results = list(executor.map(report, [a.pk, b.pk]))
                self.assertEqual(sorted(results), [200, 400])
                item.refresh_from_db()
                self.assertEqual(item.packed, 10 * (attempt + 1))
                self.assertEqual(item.produced, 10 * (attempt + 1))

    def test_two_workers_cannot_produce_the_same_packages(self):
        a = get_user_model().objects.create_superuser("reserve-a", password="test")
        b = get_user_model().objects.create_superuser("reserve-b", password="test")
        product = Product.objects.create(code="STOCK", name="Stock")
        variant = Variant.objects.create(
            product=product, sku="STOCK30", name="30g", weight_g=30
        )
        customer = Customer.objects.create(name="Customer")
        order = Order.objects.create(
            customer=customer, created_by=a, due_at=timezone.now(), delivery="pickup"
        )
        item = Item(order=order, variant=variant, quantity=10)
        s.snapshot_item(item, variant)
        item.save()
        with transaction.atomic():
            s.confirm(order, a)
        task = order.tasks.get(kind="production")
        barrier = threading.Barrier(2)

        def report(uid):
            connections.close_all()
            try:
                client = APIClient()
                client.force_login(get_user_model().objects.get(pk=uid))
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/tasks/{task.pk}/report/",
                    {"units": 10},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(report, [a.pk, b.pk]))
        self.assertEqual(sorted(results), [200, 400])
        item.refresh_from_db()
        self.assertEqual(item.produced, 10)

    def test_parallel_login_attempts_cannot_slip_past_the_limit(self):
        os_limits = patch.dict(
            "os.environ", {"LOGIN_IP_LIMIT": "30", "LOGIN_ACCOUNT_LIMIT": "10"}
        )
        os_limits.start()
        self.addCleanup(os_limits.stop)

        def once(_number):
            connections.close_all()
            try:
                client = APIClient()
                return client.post(
                    "/api/auth/login/",
                    {"username": "parallel-user", "password": "wrong-password"},
                    format="json",
                    REMOTE_ADDR="172.18.0.12",
                    HTTP_X_REAL_IP="203.0.113.80",
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=12) as executor:
            statuses = list(executor.map(once, range(16)))
        self.assertLessEqual(statuses.count(400), 10)
        self.assertGreaterEqual(statuses.count(429), 6)
        self.assertEqual(statuses.count(400) + statuses.count(429), 16)
