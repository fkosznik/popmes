import io
import json
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest import skipUnless
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
            name="Firma testowa", email="private@example.com"
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

    def order(self, quantity=200, custom=False, confirm=True):
        self.variant.custom_label = custom
        self.variant.save()
        r = self.post(
            "orders/save/",
            {
                "customer_id": self.customer.pk,
                "due_at": (timezone.now() + timedelta(days=1)).isoformat(),
                "items": [{"variant_id": self.variant.pk, "quantity": quantity}],
                "confirm": confirm,
            },
        )
        return Order.objects.get(pk=r.data["id"])

    def tasks(self, order):
        return order.tasks.get(kind="production"), order.tasks.get(kind="packing")

    def png(self):
        out = io.BytesIO()
        Image.new("RGB", (5, 5), "red").save(out, "PNG")
        out.seek(0)
        out.name = "label.png"
        return out

    def upload(self, item):
        r = self.client.post(
            f"/api/items/{item.pk}/labels/",
            {"file": self.png()},
            format="multipart",
            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
        )
        self.assertEqual(r.status_code, 200, r.content)
        return r.data["id"]

    def test_partial_full_flow_and_idempotency(self):
        order = self.order()
        p, k = self.tasks(order)
        key = uuid.uuid4()
        self.post(f"tasks/{p.pk}/report/", {"grams": "4000"}, key)
        self.post(f"tasks/{p.pk}/report/", {"grams": "4000"}, key)
        self.assertEqual(Report.objects.count(), 1)
        self.post(f"tasks/{p.pk}/report/", {"grams": "3000"}, key, 400)
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        self.assertEqual(s.available(order, self.product.pk), 1000)
        self.assertEqual(s.status(order), "in_progress")
        self.post(f"tasks/{k.pk}/report/", {"units": 100}, expected=400)
        self.post(f"tasks/{p.pk}/report/", {"grams": "2000"})
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        self.assertEqual(s.status(order), "completed")
        self.assertEqual(s.available(order, self.product.pk), 0)
        self.post(f"orders/{order.pk}/issue/")
        order.refresh_from_db()
        self.assertEqual(s.status(order), "issued")
        self.post(f"tasks/{p.pk}/report/", {"grams": 100}, expected=400)

    def test_flavor_grouping_and_frozen_snapshot(self):
        variant2 = Variant.objects.create(
            product=self.product, sku="KAR100", name="Karmel 100", weight_g=100
        )
        r = self.post(
            "orders/save/",
            {
                "customer_id": self.customer.pk,
                "due_at": timezone.now().isoformat(),
                "items": [
                    {"variant_id": self.variant.pk, "quantity": 100},
                    {"variant_id": variant2.pk, "quantity": 20},
                ],
                "confirm": True,
            },
        )
        order = Order.objects.get(pk=r.data["id"])
        self.assertEqual(order.tasks.filter(kind="production").count(), 1)
        self.assertEqual(order.tasks.get(kind="production").target_g, 5000)
        self.assertEqual(order.tasks.filter(kind="packing").count(), 2)
        self.variant.weight_g = 40
        self.variant.save()
        self.post(f"orders/{order.pk}/confirm/")
        self.assertEqual(order.items.first().weight_g, 30)
        self.assertEqual(order.tasks.count(), 3)

    def test_label_gate_version_and_download(self):
        order = self.order(custom=True)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"grams": 6000})
        self.post(f"tasks/{k.pk}/report/", {"units": 100}, expected=400)
        lid = self.upload(k.item)
        self.post(f"labels/{lid}/approve/")
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        report = Report.objects.get(task=k)
        self.assertEqual(report.label_id, lid)
        second = self.upload(k.item)
        self.post(f"tasks/{k.pk}/report/", {"units": 100}, expected=400)
        self.post(f"labels/{lid}/approve/", expected=400)
        self.post(f"labels/{second}/approve/")
        self.post(f"tasks/{k.pk}/report/", {"units": 100})
        response = self.client.get(f"/api/labels/{lid}/download/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"\x89PNG"))
        self.client.logout()
        self.assertEqual(
            self.client.get(f"/api/labels/{lid}/download/").status_code, 403
        )

    def test_waste_deficit_and_replenish_no_duplicate(self):
        order = self.order()
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"grams": 6000})
        self.post(
            f"tasks/{k.pk}/report/", {"units": 100, "grams": 3100, "waste_g": 100}
        )
        self.assertEqual(s.available(order, self.product.pk), 2900)
        self.assertEqual(s.deficits(order)[0]["shortage_g"], "100.000")
        self.post(f"orders/{order.pk}/replenish/")
        self.post(f"orders/{order.pk}/replenish/")
        self.assertEqual(order.tasks.filter(supplemental=True).count(), 1)
        self.assertEqual(order.tasks.get(supplemental=True).target_g, 100)

    def test_overpacking_invalid_mass_and_cross_order_batch(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"grams": 300})
        self.post(f"tasks/{k.pk}/report/", {"units": 11}, expected=400)
        self.post(f"tasks/{k.pk}/report/", {"units": 1.5}, expected=400)
        self.post(f"tasks/{k.pk}/report/", {"units": 1, "grams": 20}, expected=400)
        self.post(f"tasks/{p.pk}/report/", {"grams": "NaN"}, expected=400)
        other = self.order(1)
        p2, _ = self.tasks(other)
        self.post(f"tasks/{p2.pk}/report/", {"grams": 30})
        self.post(
            f"tasks/{k.pk}/report/",
            {
                "units": 1,
                "allocations": [{"batch_id": p2.batches.first().pk, "grams": 30}],
            },
            expected=400,
        )
        self.assertEqual(s.available(order, self.product.pk), 300)

    def test_hold_cancel_and_audit(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/start/")
        self.post(f"tasks/{p.pk}/report/", {"grams": 150})
        self.post(f"orders/{order.pk}/hold/", {"reason": "Brak surowca"})
        self.assertFalse(WorkSession.objects.filter(ended_at=None).exists())
        self.post(f"tasks/{p.pk}/report/", {"grams": 150}, expected=400)
        self.post(f"orders/{order.pk}/resume/")
        self.post(f"orders/{order.pk}/cancel/", {"reason": "Rezygnacja klienta"})
        self.assertEqual(s.available(order, self.product.pk), 0)
        self.assertEqual(Batch.objects.get(order=None).available_g, 150)
        self.post(f"tasks/{p.pk}/report/", {"grams": 150}, expected=400)
        self.assertTrue(order.events.filter(action="Anulowano zamówienie").exists())

    def test_corrections_preserve_reports_and_mass(self):
        order = self.order(10)
        p, k = self.tasks(order)
        r = self.post(f"tasks/{p.pk}/report/", {"grams": 300}).data["id"]
        packed = self.post(f"tasks/{k.pk}/report/", {"units": 10}).data["id"]
        self.post(f"reports/{r}/correct/", {"reason": "Błąd"}, expected=400)
        self.post(
            f"reports/{packed}/correct/",
            {"reason": "Błędne kliknięcie", "restore_mass": True},
        )
        self.assertEqual(s.available(order, self.product.pk), 300)
        self.assertEqual(order.items.first().packed, 0)
        self.post(f"reports/{r}/correct/", {"reason": "Błędny zapis"})
        self.assertEqual(s.available(order, self.product.pk), 0)
        self.assertEqual(Report.objects.count(), 2)
        self.assertEqual(Correction.objects.count(), 2)
        self.post(f"reports/{r}/correct/", {"reason": "Jeszcze raz"}, expected=400)

    def test_real_repacking_does_not_restore_mass(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"grams": 300})
        r = self.post(f"tasks/{k.pk}/report/", {"units": 10}).data["id"]
        self.post(
            f"reports/{r}/correct/",
            {"reason": "Produkt uszkodzony", "restore_mass": False},
        )
        self.assertEqual(s.available(order, self.product.pk), 0)
        self.assertEqual(s.deficits(order)[0]["shortage_g"], "300.000")

    def test_amend_conflict_and_completed_reopen(self):
        order = self.order(10)
        p, k = self.tasks(order)
        self.post(f"tasks/{p.pk}/report/", {"grams": 300})
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
        p.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(p.target_g, 600)
        self.assertEqual(s.status(order), "in_progress")
        self.assertIsNone(order.completed_at)

    def test_transfer_preserves_origin_and_ledger(self):
        source = self.order(10)
        p, _ = self.tasks(source)
        self.post(f"tasks/{p.pk}/report/", {"grams": 400})
        target = self.order(10)
        batch = p.batches.first()
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

    def test_surplus_reserved_before_new_production(self):
        source = self.order(10)
        p, _ = self.tasks(source)
        self.post(f"tasks/{p.pk}/report/", {"grams": 500})
        self.assertEqual(s.available(source, self.product.pk), 300)
        self.assertEqual(Batch.objects.get(order=None).available_g, 200)
        target = self.order(15)
        production, packing = self.tasks(target)
        self.assertEqual(production.target_g, 250)
        self.assertEqual(s.available(target, self.product.pk), 200)
        self.post(f"tasks/{packing.pk}/report/", {"units": 5})
        self.assertEqual(s.available(target, self.product.pk), 50)
        following = self.order(10)
        self.assertEqual(self.tasks(following)[0].target_g, 300)
        for batch in Batch.objects.all():
            self.assertEqual(
                sum(m.delta_g for m in batch.movements.all()), batch.available_g
            )

    def test_full_stock_cover_skips_production_and_cancel_releases(self):
        source = self.order(10)
        p, _ = self.tasks(source)
        self.post(f"tasks/{p.pk}/report/", {"grams": 600})
        target = self.order(10)
        production, _ = self.tasks(target)
        self.assertEqual(production.target_g, 0)
        self.assertTrue(s.complete(production))
        self.post(f"orders/{target.pk}/cancel/", {"reason": "Rezygnacja"})
        self.assertEqual(s.available(target, self.product.pk), 0)
        self.assertEqual(
            sum(b.available_g for b in Batch.objects.filter(order=None)), 300
        )

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


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locks required")
class ConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def test_two_workers_cannot_consume_same_batch(self):
        a = get_user_model().objects.create_superuser("a", password="test")
        b = get_user_model().objects.create_superuser("b", password="test")
        product = Product.objects.create(code="P", name="Product")
        variant = Variant.objects.create(
            product=product, sku="P30", name="30g", weight_g=30
        )
        customer = Customer.objects.create(name="Customer")
        order = Order.objects.create(
            customer=customer, created_by=a, due_at=timezone.now()
        )
        item = Item(order=order, variant=variant, quantity=100)
        s.snapshot_item(item, variant)
        item.save()
        with transaction.atomic():
            s.confirm(order, a)
            p = order.tasks.get(kind="production")
            s.production_report(p, a, {"grams": 300})
        task = order.tasks.get(kind="packing")
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
                        s.production_report(p, a, {"grams": 300})
                results = list(executor.map(report, [a.pk, b.pk]))
                self.assertEqual(sorted(results), [200, 400])
                item.refresh_from_db()
                self.assertEqual(item.packed, 10 * (attempt + 1))
                self.assertEqual(s.available(order, product.pk), 0)

    def test_two_orders_cannot_reserve_same_free_stock(self):
        a = get_user_model().objects.create_superuser("reserve-a", password="test")
        b = get_user_model().objects.create_superuser("reserve-b", password="test")
        product = Product.objects.create(code="STOCK", name="Stock")
        variant = Variant.objects.create(
            product=product, sku="STOCK30", name="30g", weight_g=30
        )
        customer = Customer.objects.create(name="Customer")

        def draft(user):
            order = Order.objects.create(
                customer=customer, created_by=user, due_at=timezone.now()
            )
            item = Item(order=order, variant=variant, quantity=10)
            s.snapshot_item(item, variant)
            item.save()
            return order

        source = draft(a)
        with transaction.atomic():
            s.confirm(source, a)
            s.production_report(source.tasks.get(kind="production"), a, {"grams": 600})
        orders = [draft(a), draft(b)]
        barrier = threading.Barrier(2)

        def confirm(pair):
            user, order = pair
            connections.close_all()
            try:
                client = APIClient()
                client.force_login(get_user_model().objects.get(pk=user.pk))
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/orders/{order.pk}/confirm/",
                    {},
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
                ).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(
                list(executor.map(confirm, zip([a, b], orders))), [200, 200]
            )
        self.assertEqual(
            sorted(o.tasks.get(kind="production").target_g for o in orders), [0, 300]
        )
        self.assertEqual(sum(s.available(o, product.pk) for o in orders), 300)
