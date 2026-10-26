"""Business operations. Call under transaction.atomic with the order row locked."""

import hashlib
from decimal import Decimal, InvalidOperation
from django.db.models import (
    Case,
    Exists,
    F,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import (
    Item,
    ItemLot,
    Label,
    Product,
    Variant,
    Task,
    Batch,
    Report,
    Movement,
    Correction,
    WorkSession,
    Event,
    Shipment,
    ShipmentLine,
    StockItem,
    StockMove,
    StockCategory,
    Order,
    Organization,
    Workspace,
    Profile,
    Supplier,
    Recipe,
    RecipeLine,
)

ROLES = ["sales", "production", "packing", "manager", "admin"]
THEMES = {"plum", "teal", "forest", "amber"}
ZERO = Decimal("0")


def organization():
    org = Organization.objects.order_by("id").first()
    if org is None:
        org = Organization.objects.create()
    return org


def primary_workspace():
    space = Workspace.objects.filter(primary=True).first()
    if space is not None:
        return space
    space = Workspace.objects.order_by("id").first()
    if space is not None:
        return space
    return Workspace.objects.create(name="POPME", primary=True, active=True)


def current_workspace(user):
    profile = (
        Profile.objects.select_related("current_workspace").filter(user=user).first()
    )
    chosen = profile.current_workspace if profile else None
    if chosen is not None and chosen.active:
        return chosen
    return primary_workspace()


def workspace_q(space, prefix=""):
    field = f"{prefix}workspace" if prefix else "workspace"
    if space.primary:
        return Q(**{field: space}) | Q(**{f"{field}__isnull": True})
    return Q(**{field: space})


def workspace_filter(user, prefix=""):
    space = current_workspace(user)
    return workspace_q(space, prefix), space


def order_visible(user, order_id):
    order_q, _space = workspace_filter(user)
    return Order.objects.filter(order_q, pk=order_id).exists()


def assert_receipt_workspace(user, path, response):
    import re

    order_id = None
    match = re.search(r"/api/(?:orders|tasks|reports|labels|items)/(\d+)", path)
    if "/api/orders/" in path and match:
        order_id = int(match.group(1))
    elif "/api/tasks/" in path and match:
        order_id = (
            Task.objects.filter(pk=int(match.group(1)))
            .values_list("order_id", flat=True)
            .first()
        )
    elif "/api/reports/" in path and match:
        order_id = (
            Report.objects.filter(pk=int(match.group(1)))
            .values_list("task__order_id", flat=True)
            .first()
        )
    elif "/api/labels/" in path and match:
        order_id = (
            Label.objects.filter(pk=int(match.group(1)))
            .values_list("item__order_id", flat=True)
            .first()
        )
    elif "/api/items/" in path and match:
        order_id = (
            Item.objects.filter(pk=int(match.group(1)))
            .values_list("order_id", flat=True)
            .first()
        )
    elif path.endswith("/orders/save/") and isinstance(response, dict):
        order_id = response.get("id")
    if order_id and not order_visible(user, order_id):
        raise PermissionDenied("To zamówienie jest w innej przestrzeni.")


def roles(user):
    return (
        ROLES if user.is_superuser else list(user.groups.values_list("name", flat=True))
    )


def permit(user, *allowed):
    if not set(roles(user)).intersection(allowed):
        raise PermissionDenied("Brak uprawnień do tej czynności.")


def decimal(value, name="Masa", positive=False):
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or number < 0
            or number > Decimal("99999999999.999")
            or number != number.quantize(Decimal(".001"))
            or (positive and number == 0)
        ):
            raise ValueError()
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(
            f"{name}: podaj poprawną liczbę, do 3 miejsc po przecinku."
        )


def integer(value, name="Liczba sztuk"):
    number = decimal(value, name, True)
    if number != int(number) or number > 10000000:
        raise ValidationError(
            f"{name}: wymagana dodatnia liczba całkowita do 10 000 000."
        )
    return int(number)


def reason(data):
    value = str(data.get("reason", "")).strip()
    if not value:
        raise ValidationError("Podaj przyczynę.")
    return value[:2000]


def event(order, user, action, **detail):
    Event.objects.create(order=order, user=user, action=action, detail=detail)
    if order:
        order.version += 1
        order.save(update_fields=["version"])


def packages_done(order, item):
    """An order line is finished when the pieces have been marked as shipped."""
    return item.packed >= item.quantity


def status(order):
    if order.cancelled_at:
        return "cancelled"
    if order.issued_at:
        return "issued"
    if not order.confirmed_at:
        return "draft"
    items = list(order.items.all())
    if items and all(packages_done(order, i) for i in items):
        return "completed"
    if any(to_produce(i) > 0 for i in items):
        return "producing"
    return "awaiting_shipment"


def available(order, product_id):
    return (
        Batch.objects.filter(order=order, product_id=product_id).aggregate(
            v=Sum("available_g")
        )["v"]
        or ZERO
    )


def latest_label(item):
    labels = list(item.labels.all())
    if not labels:
        return None
    return max(labels, key=lambda label: label.version)


def label_ready(item):
    label = latest_label(item)
    return bool(label.approved_at) if label else not item.custom_label


def to_produce(item):
    return max(0, item.quantity - item.allocated - item.produced)


def ready_to_ship(item):
    return max(0, item.allocated + item.produced - item.packed)


def complete(task):
    item = task.item
    if task.kind == "production":
        if item is None:
            return task.produced_g >= task.target_g
        return to_produce(item) == 0
    return item.packed >= item.quantity


def blockers(task):
    values = []
    if task.order.cancelled_at:
        values.append("Zamówienie anulowane")
    if task.order.issued_at:
        values.append("Zamówienie wydane")
    if task.order.hold_reason:
        values.append(task.order.hold_reason)
    if task.hold_reason:
        values.append(task.hold_reason)
    if (
        task.kind == "production"
        and task.item_id
        and not complete(task)
        and not label_ready(task.item)
    ):
        values.append("Etykieta wymaga zatwierdzenia")
    if task.kind in ("shipping", "packing") and not complete(task):
        if ready_to_ship(task.item) < 1:
            values.append("Czeka na produkcję")
    return values


def task_status(task):
    if complete(task):
        return "done"
    if task.started_at:
        return "in_progress"
    return "waiting" if blockers(task) else "ready"


def ensure_open(order):
    if order.cancelled_at or order.issued_at:
        raise ValidationError(
            "Zamówienie anulowane lub wydane. Cofnij wydanie, aby wprowadzić korektę."
        )


def ensure_task(task):
    ensure_open(task.order)
    if not task.order.confirmed_at:
        raise ValidationError("Zatwierdź zamówienie.")
    reasons = blockers(task)
    if reasons:
        raise ValidationError(" · ".join(reasons))


def stop_sessions(order=None, task=None, user=None):
    query = WorkSession.objects.filter(ended_at__isnull=True)
    if order:
        query = query.filter(task__order=order)
    if task:
        query = query.filter(task=task)
    if user:
        query = query.filter(user=user)
    query.update(ended_at=timezone.now())


def refresh_completion(order):
    done = status(order) == "completed"
    if done and not order.completed_at:
        order.completed_at = timezone.now()
    if not done:
        order.completed_at = None
    order.save(update_fields=["completed_at"])
    for task in order.tasks.select_related("item"):
        if complete(task):
            stop_sessions(task=task)


def snapshot_item(item, variant):
    item.product = variant.product
    item.name = variant.name
    item.product_name = variant.product.name
    item.weight_g = variant.weight_g
    item.packaging = variant.packaging
    item.custom_label = variant.custom_label
    item.instruction = variant.instruction or "Użyj standardowej etykiety produktu."


def confirm(order, user):
    ensure_open(order)
    if order.confirmed_at:
        return
    if (
        not order.customer
        or not order.customer.active
        or not order.due_at
        or not order.items.exists()
    ):
        raise ValidationError(
            "Wybierz aktywnego klienta, termin i co najmniej jeden produkt."
        )
    if order.delivery in ("courier", "locker") and not order.address.strip():
        raise ValidationError(
            "Dla paczkomatu podaj punkt odbioru."
            if order.delivery == "locker"
            else "Dla kuriera podaj adres dostawy."
        )
    items = list(
        order.items.select_related("variant__product").order_by("variant_id", "id")
    )
    for item in items:
        variant = item.variant
        if not variant.active or not variant.product.active:
            raise ValidationError(f"Produkt {variant.name} jest nieaktywny.")
        snapshot_item(item, variant)
        item.save()
    for item in items:
        allocate_item(item, user, order)
        item.refresh_from_db()
        if to_produce(item) > 0:
            Task.objects.create(
                order=order,
                kind="production",
                product=item.product,
                product_name=item.name,
                item=item,
                instruction=item.variant.product.instruction,
            )
        Task.objects.create(
            order=order,
            kind="shipping",
            product=item.product,
            product_name=item.name,
            item=item,
            instruction=item.instruction,
        )
    customer = order.customer
    order.customer_snapshot = {
        field: getattr(customer, field)
        for field in ["name", "contact", "email", "phone", "tax_id", "address"]
    }
    order.confirmed_at = timezone.now()
    order.save()
    event(order, user, "Zatwierdzono zamówienie")


def movement(batch, order, user, delta, why, report=None):
    if batch.available_g + delta < 0:
        raise ValidationError("Niewystarczająca masa partii. Odśwież dane.")
    batch.available_g += delta
    batch.save(update_fields=["available_g"])
    Movement.objects.create(
        batch=batch, order=order, user=user, delta_g=delta, reason=why, report=report
    )


def start(task, user):
    ensure_task(task)
    if complete(task):
        raise ValidationError("Zadanie jest już wykonane.")
    if not task.started_at:
        task.started_at = timezone.now()
        task.save(update_fields=["started_at"])
    WorkSession.objects.get_or_create(task=task, user=user, ended_at=None)
    event(task.order, user, "Rozpoczęto pracę", task_id=task.pk, stage=task.kind)


def locked_item(task):
    if not task.item_id:
        raise ValidationError("To zlecenie nie dotyczy konkretnego opakowania.")
    item = Item.objects.select_for_update().get(pk=task.item_id)
    task.item = item
    return item


def approved_label(item):
    label = latest_label(item)
    if label and label.approved_at:
        return label
    return None


def production_report(task, user, data):
    ensure_task(task)
    item = locked_item(task)
    units = integer(data.get("units"), "Liczba opakowań")
    # The order keeps its quantity. Packs beyond it stay in the warehouse,
    # unreserved, so another order can use them.
    for_order = min(units, to_produce(item))
    surplus = units - for_order
    report = Report.objects.create(
        task=task,
        user=user,
        units=units,
        label=approved_label(item),
        note=str(data.get("note", ""))[:4000],
    )
    if for_order:
        item.produced += for_order
        item.save(update_fields=["produced"])
        add_finished(item, for_order, user, report, "Produkcja opakowań")
    if surplus:
        add_free_finished(item, surplus, user, report, "Nadwyżka produkcji")
    consume_recipe(item.variant, units, user, report)
    task.started_at = task.started_at or timezone.now()
    task.save(update_fields=["started_at"])
    refresh_completion(task.order)
    event(
        task.order,
        user,
        "Zgłoszono opakowania",
        report_id=report.pk,
        units=units,
        for_order=for_order,
        surplus=surplus,
        item=item.name,
    )
    return report


def packing_report(task, user, data):
    return shipping_report(task, user, data)


def shipping_report(task, user, data):
    ensure_task(task)
    order = task.order
    item = locked_item(task)
    units = integer(data.get("units"), "Liczba opakowań")
    if units > item.quantity - item.packed:
        raise ValidationError("Liczba przekracza pozostałe opakowania w zamówieniu.")
    if units > ready_to_ship(item):
        raise ValidationError(
            "Za mało gotowych opakowań. Najpierw dokończ produkcję albo użyj stanu z magazynu."
        )
    note = str(data.get("note", ""))[:4000]
    ensure_shippable_artwork(item, units)
    report = Report.objects.create(
        task=task,
        user=user,
        units=units,
        label=None,
        note=note,
    )
    shipment = Shipment.objects.create(
        order=order, created_by=user, address=order.address, note=note
    )
    ShipmentLine.objects.create(
        shipment=shipment, item=item, units=units, report=report
    )
    item.packed += units
    item.save(update_fields=["packed"])
    consumed = remove_finished(item, units, user, report, "Wysłano")
    label_id = label_for_consumed(consumed)
    if label_id:
        report.label_id = label_id
        report.save(update_fields=["label"])
    task.started_at = task.started_at or timezone.now()
    task.save(update_fields=["started_at"])
    refresh_completion(order)
    event(
        order,
        user,
        "Oznaczono wysyłkę",
        report_id=report.pk,
        shipment=shipment.number,
        units=units,
        item=item.name,
    )
    return report


def ship_order(order, user):
    ensure_open(order)
    if not order.confirmed_at:
        raise ValidationError("Zatwierdź zamówienie.")
    if order.hold_reason:
        raise ValidationError(order.hold_reason)
    items = list(Item.objects.select_for_update().filter(order=order).order_by("id"))
    pending = []
    for item in items:
        left = item.quantity - item.packed
        if left <= 0:
            continue
        ensure_shippable_artwork(item, left)
        if ready_to_ship(item) < left:
            raise ValidationError(
                "Czeka na produkcję. Oznacz wysyłkę, gdy całe zamówienie jest gotowe."
            )
        pending.append((item, left))
    if not pending:
        raise ValidationError("To zamówienie jest już wysłane.")
    held = (
        Task.objects.filter(order=order, kind__in=["shipping", "packing"])
        .exclude(hold_reason="")
        .first()
    )
    if held:
        raise ValidationError(held.hold_reason)
    note = order.packing_notes[:4000]
    shipment = Shipment.objects.create(
        order=order, created_by=user, address=order.address, note=note
    )
    total = 0
    names = []
    for item, units in sorted(pending, key=lambda pair: (pair[0].variant_id, pair[0].id)):
        task = (
            Task.objects.filter(
                order=order, item=item, kind__in=["shipping", "packing"]
            )
            .order_by("id")
            .first()
        )
        if task is None:
            task = Task.objects.create(
                order=order,
                kind="shipping",
                product=item.product,
                product_name=item.name,
                item=item,
                instruction=item.instruction,
            )
        report = Report.objects.create(
            task=task,
            user=user,
            units=units,
            label=None,
            note=note,
        )
        ShipmentLine.objects.create(
            shipment=shipment, item=item, units=units, report=report
        )
        item.packed += units
        item.save(update_fields=["packed"])
        consumed = remove_finished(item, units, user, report, "Wysłano")
        label_id = label_for_consumed(consumed)
        if label_id:
            report.label_id = label_id
            report.save(update_fields=["label"])
        task.started_at = task.started_at or timezone.now()
        task.save(update_fields=["started_at"])
        total += units
        names.append(f"{units} × {item.name}")
    refresh_completion(order)
    event(
        order,
        user,
        "Oznaczono wysyłkę",
        shipment=shipment.number,
        units=total,
        items=", ".join(names),
    )
    return shipment


def deficits(order):
    return [
        {
            "product_id": item.product_id,
            "needed_g": "0",
            "available_g": "0",
            "planned_g": "0",
            "shortage_g": "0",
        }
        for item in order.items.all()
    ]


def replenish(order, user):
    raise ValidationError(
        "Produkcja jest liczona w opakowaniach. Pozostałą liczbę zgłoś na zleceniu produkcji."
    )


def reverse_report(report, user, data):
    task = report.task
    order = task.order
    ensure_open(order)
    if hasattr(report, "correction"):
        raise ValidationError("Raport został już skorygowany.")
    why = reason(data)
    restore = data.get("restore_mass") is True
    if task.kind == "production":
        if report.units and task.item_id:
            item = locked_item(task)
            order_units = sum(
                int(move.reserved_delta)
                for move in StockMove.objects.filter(
                    report=report, delta__gt=0, reserved_delta__gt=0
                )
            )
            if order_units > item.produced:
                raise ValidationError("Raport nie pasuje do wyprodukowanej ilości.")
            if item.allocated + item.produced - order_units < item.packed:
                raise ValidationError(
                    "Najpierw cofnij wysyłkę tych opakowań."
                )
            reverse_custom_holds(item, report)
            item.produced -= order_units
            item.save(update_fields=["produced"])
            reverse_stock(report, user, "Korekta produkcji: " + why)
        elif report.batch_id:
            batch = Batch.objects.select_for_update().get(pk=report.batch_id)
            if batch.order_id != order.pk:
                raise ValidationError(
                    "Partia została przeniesiona. Najpierw rozlicz transfer."
                )
            movement(batch, order, user, -report.grams, "Korekta produkcji: " + why)
            task.produced_g -= report.grams
            task.save(update_fields=["produced_g"])
        else:
            raise ValidationError("Nie można skorygować tego raportu.")
    else:
        item = locked_item(task)
        if item.packed < report.units:
            raise ValidationError("Raport nie pasuje do stanu przesyłki.")
        reverse_custom_holds(item, report)
        item.packed -= report.units
        item.save(update_fields=["packed"])
        reverse_stock(report, user, "Korekta wysyłki: " + why)
        if restore:
            for original in report.movements.all():
                batch = Batch.objects.select_for_update().get(pk=original.batch_id)
                if batch.order_id != order.pk:
                    raise ValidationError(
                        "Partia została przeniesiona. Najpierw rozlicz transfer."
                    )
                movement(
                    batch,
                    order,
                    user,
                    -original.delta_g,
                    "Cofnięcie błędnego zapisu pakowania: " + why,
                )
    Correction.objects.create(
        report=report, user=user, reason=why, restored_mass=restore
    )
    refresh_completion(order)
    event(
        order,
        user,
        "Skorygowano raport",
        report_id=report.pk,
        reason=why,
        restore_mass=restore,
    )


def amend(order, user, data):
    ensure_open(order)
    if int(data.get("version", -1)) != order.version:
        raise ValidationError("Zamówienie zmieniło się. Odśwież dane przed edycją.")
    started = order.tasks.filter(started_at__isnull=False).exists()
    if started:
        permit(user, "manager")
    else:
        permit(user, "sales", "manager")
    why = reason(data)
    before = {
        "due_at": str(order.due_at),
        "priority": order.priority,
        "items": list(order.items.values("id", "quantity")),
    }
    # Confirmed items retain their identity, label history and product snapshots.
    touched = []
    for change in data.get("items", []):
        item = order.items.filter(pk=change.get("id")).first()
        if not item:
            raise ValidationError("Pozycja nie należy do zamówienia.")
        qty = integer(change.get("quantity"))
        if qty < item.packed:
            raise ValidationError("Najpierw cofnij wysyłkę tych opakowań.")
        covered = item.allocated + item.produced
        if qty < covered:
            release_covered(item, covered - qty, user, "Zmiana ilości: " + why)
            item.refresh_from_db()
        item.quantity = qty
        item.save(update_fields=["quantity"])
        if to_produce(item) > 0 and not item.tasks.filter(kind="production").exists():
            Task.objects.create(
                order=order,
                kind="production",
                product=item.product,
                product_name=item.name,
                item=item,
                instruction=item.instruction,
            )
        if not item.tasks.filter(kind="shipping").exists():
            Task.objects.create(
                order=order,
                kind="shipping",
                product=item.product,
                product_name=item.name,
                item=item,
                instruction=item.instruction,
            )
        touched.append(item)
    # Quantity is already saved, so freed packs can be reserved again.
    # Lock lots by primary key, then the shared pool.
    for item in touched:
        if item.custom_label:
            for stock_id in item.lots.values_list("stock_id", flat=True).order_by("stock_id"):
                assign_stock(StockItem.objects.select_for_update().get(pk=stock_id), user)
        else:
            assign_available(item.variant, user)
    if "priority" in data:
        if data["priority"] not in ["normal", "urgent"]:
            raise ValidationError("Niepoprawny priorytet.")
        order.priority = data["priority"]
    if "due_at" in data:
        from rest_framework.fields import DateTimeField

        order.due_at = DateTimeField().run_validation(data["due_at"])
    for field in ["production_notes", "packing_notes", "internal_notes"]:
        if field in data:
            setattr(order, field, str(data[field])[:4000])
    order.save()
    refresh_completion(order)
    event(
        order,
        user,
        "Zmieniono zamówienie",
        reason=why,
        before=before,
        after={
            "due_at": str(order.due_at),
            "priority": order.priority,
            "items": list(order.items.values("id", "quantity")),
        },
    )


def lock_products(ids):
    # NO KEY UPDATE keeps FK checks compatible while serializing each flavor.
    list(
        Product.objects.select_for_update(no_key=True).filter(pk__in=ids).order_by("pk")
    )


def reserve_stock(order, product_id, needed, user):
    remaining = needed
    for batch in (
        Batch.objects.select_for_update()
        .filter(order__isnull=True, product_id=product_id, available_g__gt=0)
        .order_by("created_at", "pk")
    ):
        amount = min(remaining, batch.available_g)
        if amount <= 0:
            break
        movement(batch, None, user, -amount, "Rezerwacja dla " + order.number)
        allocated = Batch.objects.create(
            origin=batch.origin,
            order=order,
            product_id=product_id,
            created_at=batch.created_at,
        )
        movement(allocated, order, user, amount, "Z magazynu: " + batch.number)
        event(
            order,
            user,
            "Przydzielono zapas",
            source=batch.number,
            batch=allocated.number,
            grams=str(amount),
        )
        remaining -= amount
    return needed - remaining


def release_surplus(order, user):
    ids = list(order.items.values_list("product_id", flat=True).distinct())
    lock_products(ids)
    for pid in sorted(ids):
        needed = (
            ZERO
            if order.cancelled_at
            else sum(
                (
                    (i.quantity - i.packed) * i.weight_g
                    for i in order.items.filter(product_id=pid)
                ),
                ZERO,
            )
        )
        extra = max(ZERO, available(order, pid) - needed)
        for batch in (
            Batch.objects.select_for_update()
            .filter(order=order, product_id=pid, available_g__gt=0)
            .order_by("-created_at", "-pk")
        ):
            amount = min(extra, batch.available_g)
            if amount <= 0:
                break
            movement(batch, order, user, -amount, "Nadwyżka do magazynu")
            free = Batch.objects.create(
                origin=batch.origin,
                order=None,
                product_id=pid,
                created_at=batch.created_at,
            )
            movement(free, None, user, amount, "Nadwyżka z " + batch.number)
            event(
                order,
                user,
                "Przekazano nadwyżkę do magazynu",
                batch=free.number,
                grams=str(amount),
            )
            extra -= amount


def grams_label(value):
    number = Decimal(value)
    if number == number.to_integral():
        return str(int(number))
    return format(number.normalize(), "f")


def ensure_stock_catalog():
    materials = [
        ("CUKIER", "Cukier", "ingredient", "kg", 10),
        ("MASLO", "Masło", "ingredient", "kg", 20),
        ("SOL", "Sól", "ingredient", "kg", 30),
        ("SYROP", "Syrop glukozowy", "ingredient", "kg", 40),
    ]
    for grams in (15, 30, 100, 400):
        materials.append(
            (f"OPAK-{grams}", f"Opakowanie {grams} g", "packaging", "szt", grams)
        )
        materials.append(
            (
                f"ETY-{grams}-PRZOD",
                f"Etykieta {grams} g — przód",
                "label",
                "szt",
                grams * 10 + 1,
            )
        )
        materials.append(
            (
                f"ETY-{grams}-TYL",
                f"Etykieta {grams} g — tył",
                "label",
                "szt",
                grams * 10 + 2,
            )
        )
    for code, name, group, unit, position in materials:
        StockItem.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "group": group,
                "unit": unit,
                "position": position,
            },
        )
    for variant in Variant.objects.filter(active=True):
        ensure_plain_stock(variant)


def finished_category():
    category, _ = StockCategory.objects.get_or_create(
        system=True, defaults={"name": "Produkty", "position": 0}
    )
    return category


def plain_stock_defaults(variant, category):
    return {
        "code": f"POP-{variant.sku}"[:40],
        "name": f"{variant.name} · {grams_label(variant.weight_g)} g",
        "group": "popcorn",
        "unit": "szt",
        "position": int(variant.weight_g),
        "category": category,
    }


def ensure_plain_stock(variant):
    """Create the shared pool for a catalog variant. Does not rewrite existing rows."""
    category = finished_category()
    stock, _ = StockItem.objects.get_or_create(
        variant=variant,
        artwork_sha256="",
        artwork_unknown=False,
        defaults=plain_stock_defaults(variant, category),
    )
    return stock


def sync_catalog_stock(variant=None):
    """Refresh plain catalog rows after a catalog change. Never touches logo lots."""
    category = finished_category()
    variants = (
        [variant]
        if variant is not None
        else Variant.objects.select_related("product")
    )
    for row in variants:
        StockItem.objects.update_or_create(
            variant=row,
            artwork_sha256="",
            artwork_unknown=False,
            defaults=plain_stock_defaults(row, category),
        )


def file_sha256(content):
    return hashlib.sha256(content).hexdigest()


def record_move(stock, quantity_delta, reserved_delta, user, reason, report=None):
    stock.quantity += Decimal(quantity_delta)
    stock.reserved += Decimal(reserved_delta)
    if stock.quantity < 0 or stock.reserved < 0:
        raise ValidationError("Stan magazynu spadłby poniżej zera.")
    if stock.quantity < stock.reserved:
        raise ValidationError("Za mało towaru w magazynie.")
    stock.save(update_fields=["quantity", "reserved"])
    StockMove.objects.create(
        item=stock,
        delta=quantity_delta,
        reserved_delta=reserved_delta,
        quantity_after=stock.quantity,
        reason=reason[:2000],
        user=user,
        report=report,
    )


def variant_stock_locked(variant):
    # Shared pool only. Logo lots are separate rows and must not be locked here.
    stock = (
        StockItem.objects.select_for_update()
        .filter(variant=variant, artwork_sha256="", artwork_unknown=False)
        .order_by("pk")
        .first()
    )
    if stock is None:
        ensure_plain_stock(variant)
        stock = StockItem.objects.select_for_update().get(
            variant=variant, artwork_sha256="", artwork_unknown=False
        )
    return stock


def artwork_code(variant, version, digest):
    base = f"L{variant.pk}V{version}{digest[:10]}".upper()
    code = base[:40]
    number = 2
    while StockItem.objects.filter(code=code).exists():
        suffix = f"-{number}"
        code = f"{base[:40 - len(suffix)]}{suffix}"
        number += 1
    return code


def artwork_stock_locked(variant, label):
    if not label.content_sha256:
        raise ValidationError("Etykieta nie ma identyfikatora grafiki.")
    stock = (
        StockItem.objects.select_for_update()
        .filter(
            variant=variant,
            artwork_sha256=label.content_sha256,
            artwork_version=label.version,
            artwork_unknown=False,
        )
        .first()
    )
    if stock is not None:
        return stock
    category = finished_category()
    stock, _ = StockItem.objects.get_or_create(
        variant=variant,
        artwork_sha256=label.content_sha256,
        artwork_version=label.version,
        artwork_unknown=False,
        defaults={
            "code": artwork_code(variant, label.version, label.content_sha256),
            "name": (
                f"{variant.name} · {grams_label(variant.weight_g)} g"
                f" · etykieta v{label.version}"
            )[:180],
            "group": "popcorn",
            "unit": "szt",
            "position": int(variant.weight_g),
            "category": category,
            "label": label,
        },
    )
    return StockItem.objects.select_for_update().get(pk=stock.pk)


def remember_hold(item, stock, allocated=0, produced=0):
    hold, _ = ItemLot.objects.get_or_create(item=item, stock=stock)
    hold = ItemLot.objects.select_for_update().get(pk=hold.pk)
    if allocated:
        hold.allocated += allocated
    if produced:
        hold.produced += produced
    hold.save(update_fields=["allocated", "produced"])
    return hold


def add_finished(item, units, user, report, reason):
    if item.custom_label:
        label = approved_label(item)
        if label is None:
            raise ValidationError("Zatwierdź etykietę przed produkcją.")
        stock = artwork_stock_locked(item.variant, label)
        record_move(stock, units, units, user, reason, report)
        remember_hold(item, stock, produced=units)
        return stock
    return adjust_variant(item.variant, units, units, user, reason, report)


def add_free_finished(item, units, user, report, reason):
    """Put packs that exceed the order into stock without reserving them."""
    if item.custom_label:
        label = approved_label(item)
        if label is None:
            raise ValidationError("Zatwierdź etykietę przed produkcją.")
        stock = artwork_stock_locked(item.variant, label)
        record_move(stock, units, 0, user, reason, report)
        return stock
    return adjust_variant(item.variant, units, 0, user, reason, report)


def hold_matches_label(hold, label):
    stock = hold.stock
    if stock.artwork_unknown or label is None or not label.content_sha256:
        return False
    return (
        stock.artwork_sha256 == label.content_sha256
        and stock.artwork_version == label.version
    )


def conflicting_holds(item, label):
    holds = ItemLot.objects.select_related("stock").filter(item=item).order_by("id")
    return [
        hold
        for hold in holds
        if hold.allocated + hold.produced - hold.packed > 0
        and not hold_matches_label(hold, label)
    ]


def matching_ready(item, label):
    total = 0
    for hold in ItemLot.objects.select_related("stock").filter(item=item):
        if hold_matches_label(hold, label):
            total += hold.allocated + hold.produced - hold.packed
    return total


def ensure_shippable_artwork(item, units):
    if not item.custom_label:
        return
    label = latest_label(item)
    if label is None or not label.approved_at:
        raise ValidationError(
            "Zatwierdź aktualną etykietę. Nie wyślę opakowań innej grafiki."
        )
    if matching_ready(item, label) < units:
        if ready_to_ship(item) >= units:
            raise ValidationError(
                "Zarezerwowane opakowania mają inną grafikę niż zatwierdzona etykieta. "
                "Rozlicz wcześniejszy zapas, zanim wyślesz."
            )
        raise ValidationError("Za mało gotowych opakowań tej grafiki.")


def settle_previous_artwork(item, label, user):
    """Return unshipped packs of another graphic to their own lot.

    Quantity stays on that lot. This order stops claiming them. Reports and
    stock history stay.
    """
    conflict_ids = [hold.pk for hold in conflicting_holds(item, label)]
    if not conflict_ids:
        return
    holds = list(
        ItemLot.objects.select_for_update()
        .select_related("stock")
        .filter(pk__in=conflict_ids)
        .order_by("id")
    )
    locked = lock_stocks([hold.stock_id for hold in holds])
    drop_allocated = 0
    drop_produced = 0
    for hold in holds:
        unshipped = hold.allocated + hold.produced - hold.packed
        if unshipped <= 0:
            continue
        record_move(
            locked[hold.stock_id],
            0,
            -unshipped,
            user,
            "Rozliczenie wcześniejszej grafiki",
        )
        take_produced = min(hold.produced, unshipped)
        take_allocated = unshipped - take_produced
        if take_allocated > hold.allocated:
            raise ValidationError("Nie można rozliczyć wcześniejszej grafiki.")
        hold.produced -= take_produced
        hold.allocated -= take_allocated
        hold.save(update_fields=["allocated", "produced"])
        drop_produced += take_produced
        drop_allocated += take_allocated
    item.produced -= drop_produced
    item.allocated -= drop_allocated
    if item.produced < 0 or item.allocated < 0:
        raise ValidationError("Nie można rozliczyć wcześniejszej grafiki.")
    item.save(update_fields=["produced", "allocated"])
    if to_produce(item) > 0 and not item.tasks.filter(kind="production").exists():
        Task.objects.create(
            order=item.order,
            kind="production",
            product=item.product,
            product_name=item.name,
            item=item,
            instruction=item.instruction,
        )


def label_for_consumed(consumed):
    labels = []
    for stock, _units in consumed:
        if stock.label_id and stock.label_id not in labels:
            labels.append(stock.label_id)
    if len(labels) == 1:
        return labels[0]
    return None


def remove_finished(item, units, user, report, reason):
    if not item.custom_label:
        stock = adjust_variant(item.variant, -units, -units, user, reason, report)
        return [(stock, units)]
    ensure_shippable_artwork(item, units)
    label = latest_label(item)
    holds = list(
        ItemLot.objects.select_for_update().filter(item=item).order_by("id")
    )
    locked = lock_stocks([hold.stock_id for hold in holds])
    for hold in holds:
        hold.stock = locked[hold.stock_id]
    left = units
    consumed = []
    for hold in holds:
        if not hold_matches_label(hold, label):
            continue
        ready = hold.allocated + hold.produced - hold.packed
        take = min(left, ready)
        if take <= 0:
            continue
        hold.packed += take
        hold.save(update_fields=["packed"])
        stock = locked[hold.stock_id]
        record_move(stock, -take, -take, user, reason, report)
        consumed.append((stock, take))
        left -= take
    if left:
        raise ValidationError("Za mało gotowych opakowań tego projektu etykiety.")
    return consumed


def reverse_custom_holds(item, report):
    if not item.custom_label:
        return
    for move in StockMove.objects.filter(report=report).order_by("id"):
        hold = (
            ItemLot.objects.select_for_update()
            .filter(item=item, stock_id=move.item_id)
            .first()
        )
        if hold is None:
            if move.delta > 0 and move.reserved_delta == 0:
                continue
            raise ValidationError("Korekta nie znajduje partii etykiety.")
        if move.delta > 0 and hold.produced < int(move.delta):
            raise ValidationError(
                "Ta produkcja została rozliczona przy zmianie grafiki. "
                "Korekta nie cofnie zwolnionego zapasu."
            )
        if move.delta > 0:
            hold.produced -= int(move.delta)
        if move.delta < 0:
            hold.packed -= int(-move.delta)
        if hold.produced < 0 or hold.allocated < 0 or hold.packed < 0:
            raise ValidationError("Korekta rozjechałaby partię etykiety.")
        hold.save(update_fields=["allocated", "produced", "packed"])


def lock_stocks(stock_ids):
    ids = sorted({pk for pk in stock_ids if pk})
    return {
        row.pk: row
        for row in StockItem.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    }


def adjust_variant(variant, quantity_delta, reserved_delta, user, reason, report=None):
    stock = variant_stock_locked(variant)
    record_move(stock, quantity_delta, reserved_delta, user, reason, report)
    return stock


def take_free(item, stock, user, order, track_lot):
    free = stock.quantity - stock.reserved
    take = min(to_produce(item), int(free)) if free > 0 else 0
    if take <= 0:
        return 0
    item.allocated += take
    item.save(update_fields=["allocated"])
    if track_lot:
        remember_hold(item, stock, allocated=take)
    record_move(stock, 0, take, user, f"Rezerwacja do {order.number}")
    return take


def allocate_custom(item, user, order):
    label = approved_label(item)
    if label is None or not label.content_sha256:
        return 0
    stock = (
        StockItem.objects.select_for_update()
        .filter(
            variant=item.variant,
            artwork_sha256=label.content_sha256,
            artwork_version=label.version,
            artwork_unknown=False,
        )
        .first()
    )
    if stock is None:
        return 0
    return take_free(item, stock, user, order, True)


def allocate_item(item, user, order):
    if item.custom_label:
        return allocate_custom(item, user, order)
    return take_free(item, variant_stock_locked(item.variant), user, order, False)


def open_item_ids(variant, custom):
    return list(
        Item.objects.filter(
            variant=variant,
            custom_label=custom,
            order__confirmed_at__isnull=False,
            order__cancelled_at__isnull=True,
            order__issued_at__isnull=True,
        )
        .values_list("order_id", flat=True)
        .distinct()
    )


def lock_open_orders(order_ids):
    if not order_ids:
        return []
    return list(
        Order.objects.select_for_update(skip_locked=True)
        .filter(pk__in=order_ids)
        .order_by("id")
        .values_list("pk", flat=True)
    )


def give_free(stock, items, user, match):
    for item in items:
        if match is not None and not match(item):
            continue
        need = to_produce(item)
        free = stock.quantity - stock.reserved
        take = min(need, int(free)) if free > 0 else 0
        if take <= 0:
            if free <= 0:
                break
            continue
        item.allocated += take
        item.save(update_fields=["allocated"])
        if item.custom_label:
            remember_hold(item, stock, allocated=take)
        record_move(stock, 0, take, user, f"Rezerwacja do {item.order.number}")
        refresh_completion(item.order)


def items_for_orders(variant, order_ids):
    return Item.objects.select_for_update().filter(
        variant=variant, order_id__in=order_ids
    ).select_related("order").order_by("-order__priority", "order__due_at", "id")


def assign_plain_locked(stock, user):
    locked_ids = lock_open_orders(open_item_ids(stock.variant, False))
    if not locked_ids:
        return
    give_free(stock, items_for_orders(stock.variant, locked_ids), user, None)


def assign_matching_artwork(stock, user):
    locked_ids = lock_open_orders(open_item_ids(stock.variant, True))
    if not locked_ids:
        return

    def matches(item):
        label = approved_label(item)
        return bool(
            label
            and label.content_sha256 == stock.artwork_sha256
            and label.version == stock.artwork_version
        )

    give_free(stock, items_for_orders(stock.variant, locked_ids), user, matches)


def assign_stock(stock, user):
    if not stock.variant_id or stock.artwork_unknown:
        return
    if stock.artwork_sha256:
        assign_matching_artwork(stock, user)
    else:
        assign_plain_locked(stock, user)


def assign_available(variant, user):
    assign_plain_locked(variant_stock_locked(variant), user)


def release_covered(item, units, user, why):
    if item.custom_label:
        release_custom_covered(item, units, user, why)
        return
    stock = variant_stock_locked(item.variant)
    drop_produced = min(item.produced, units)
    item.produced -= drop_produced
    left = units - drop_produced
    drop_allocated = min(item.allocated, left)
    item.allocated -= drop_allocated
    item.save(update_fields=["produced", "allocated"])
    released = drop_produced + drop_allocated
    if released:
        record_move(stock, 0, -released, user, why)


def release_custom_covered(item, units, user, why):
    drop_produced = min(item.produced, units)
    drop_allocated = min(item.allocated, units - drop_produced)
    item.produced -= drop_produced
    item.allocated -= drop_allocated
    item.save(update_fields=["produced", "allocated"])
    holds = list(
        ItemLot.objects.select_for_update().filter(item=item).order_by("-id")
    )
    locked = lock_stocks([hold.stock_id for hold in holds])
    left_produced = drop_produced
    left_allocated = drop_allocated
    released = {}
    for hold in holds:
        if not left_produced:
            break
        room = hold.allocated + hold.produced - hold.packed
        take = min(left_produced, hold.produced, room)
        if take <= 0:
            continue
        hold.produced -= take
        left_produced -= take
        released[hold.stock_id] = released.get(hold.stock_id, 0) + take
    for hold in holds:
        if not left_allocated:
            break
        room = hold.allocated + hold.produced - hold.packed
        take = min(left_allocated, hold.allocated, room)
        if take <= 0:
            continue
        hold.allocated -= take
        left_allocated -= take
        released[hold.stock_id] = released.get(hold.stock_id, 0) + take
    for hold in holds:
        hold.save(update_fields=["produced", "allocated"])
    if left_produced or left_allocated:
        raise ValidationError(
            "Nie można zdjąć rezerwacji etykiety — brak powiązania partii."
        )
    for stock_id in sorted(released):
        record_move(locked[stock_id], 0, -released[stock_id], user, why)


def release_unshipped(order, user, why):
    # Stock rows are locked by primary key inside each item before the next item.
    stocks = []
    for item in order.items.select_related("variant").order_by("id"):
        held = ready_to_ship(item)
        if held <= 0:
            continue
        if item.custom_label:
            stocks.extend(release_custom_unshipped(item, held, user, why))
        else:
            stock = variant_stock_locked(item.variant)
            record_move(stock, 0, -held, user, why)
            stocks.append(stock)
    seen = set()
    for stock in stocks:
        if stock.pk in seen:
            continue
        seen.add(stock.pk)
        assign_stock(stock, user)


def release_custom_unshipped(item, held, user, why):
    holds = list(ItemLot.objects.select_for_update().filter(item=item).order_by("id"))
    locked = lock_stocks([hold.stock_id for hold in holds])
    left = held
    touched = []
    for hold in holds:
        unshipped = hold.allocated + hold.produced - hold.packed
        take = min(left, unshipped)
        if take <= 0:
            continue
        record_move(locked[hold.stock_id], 0, -take, user, why)
        touched.append(locked[hold.stock_id])
        left -= take
    if left:
        raise ValidationError(
            "Nie można zwolnić zapasu etykiety — brak powiązania partii."
        )
    return touched


def apply_stock_delta(stock, delta, user, reason, report=None):
    record_move(stock, delta, 0, user, reason, report)


def reverse_stock(report, user, reason):
    moves = list(StockMove.objects.filter(report=report).order_by("id"))
    if not moves:
        return
    locked = {
        row.pk: row
        for row in StockItem.objects.select_for_update()
        .filter(pk__in={move.item_id for move in moves})
        .order_by("pk")
    }
    for move in reversed(moves):
        record_move(
            locked[move.item_id],
            -move.delta,
            -move.reserved_delta,
            user,
            reason,
        )


def stock_rows():
    return StockItem.objects.select_related(
        "category", "supplier", "label", "variant"
    ).order_by(
        "category__position", "position", "name"
    )


def category_rows():
    return StockCategory.objects.order_by("position", "name")


def add_category(name):
    cleaned = " ".join(str(name or "").split())
    if not cleaned or len(cleaned) > 80:
        raise ValidationError("Podaj nazwę kategorii, do 80 znaków.")
    if StockCategory.objects.filter(name__iexact=cleaned).exists():
        raise ValidationError("Taka kategoria już istnieje.")
    position = (StockCategory.objects.aggregate(v=Max("position"))["v"] or 0) + 10
    return StockCategory.objects.create(name=cleaned, position=position)


def stock_code(name):
    base = "".join(ch for ch in name.upper() if ch.isalnum())[:20] or "POZ"
    code = base
    number = 2
    while StockItem.objects.filter(code=code).exists():
        suffix = f"-{number}"
        code = f"{base[:40 - len(suffix)]}{suffix}"
        number += 1
    return code


def add_supplier(data):
    name = " ".join(str(data.get("name") or "").split())
    if not name or len(name) > 180:
        raise ValidationError("Podaj nazwę dostawcy, do 180 znaków.")
    if Supplier.objects.filter(name__iexact=name).exists():
        raise ValidationError("Taki dostawca już istnieje.")
    email = str(data.get("email") or "").strip()
    if email and "@" not in email:
        raise ValidationError("Podaj poprawny e-mail dostawcy.")
    return Supplier.objects.create(
        name=name,
        contact=str(data.get("contact") or "")[:180],
        email=email,
        phone=str(data.get("phone") or "")[:50],
    )


def supplier_or_none(supplier_id):
    if supplier_id in (None, "", 0, "0"):
        return None
    supplier = Supplier.objects.filter(pk=supplier_id, active=True).first()
    if supplier is None:
        raise ValidationError("Wybierz dostawcę.")
    return supplier


def assign_supplier(stock_id, supplier_id):
    stock = StockItem.objects.select_for_update().get(pk=stock_id)
    if stock.variant_id:
        raise ValidationError(
            "Dostawcę ustawiasz przy surowcu, nie przy gotowym popcornie."
        )
    stock.supplier = supplier_or_none(supplier_id)
    stock.save(update_fields=["supplier"])
    return stock


def update_supplier(supplier_id, data):
    supplier = Supplier.objects.select_for_update().get(pk=supplier_id)
    name = " ".join(str(data.get("name") or "").split())
    if not name or len(name) > 180:
        raise ValidationError("Podaj nazwę dostawcy, do 180 znaków.")
    if Supplier.objects.filter(name__iexact=name).exclude(pk=supplier.pk).exists():
        raise ValidationError("Taki dostawca już istnieje.")
    email = str(data.get("email") or "").strip()
    if email and "@" not in email:
        raise ValidationError("Podaj poprawny e-mail dostawcy.")
    supplier.name = name
    supplier.contact = str(data.get("contact") or "")[:180]
    supplier.email = email
    supplier.phone = str(data.get("phone") or "")[:50]
    supplier.save(update_fields=["name", "contact", "email", "phone"])
    return supplier


def update_stock_item(stock_id, data):
    stock = StockItem.objects.select_for_update().get(pk=stock_id)
    if stock.variant_id:
        raise ValidationError("Ten produkt edytujesz w katalogu.")
    name = " ".join(str(data.get("name") or "").split())
    if not name or len(name) > 180:
        raise ValidationError("Podaj nazwę.")
    category = StockCategory.objects.filter(pk=data.get("category_id")).first()
    if category is None or category.system:
        raise ValidationError("Wybierz kategorię.")
    unit = data.get("unit")
    if unit not in ("szt", "kg"):
        raise ValidationError("Jednostka to szt albo kg.")
    if unit != stock.unit and (stock.quantity != 0 or stock.reserved != 0):
        raise ValidationError(
            "Jednostkę zmienisz, gdy stan i rezerwacja są zerowe."
        )
    stock.name = name
    stock.category = category
    stock.unit = unit
    stock.supplier = supplier_or_none(data.get("supplier_id"))
    stock.save(update_fields=["name", "category", "unit", "supplier"])
    return stock


def save_recipe(variant_id, lines):
    variant = Variant.objects.filter(pk=variant_id).first()
    if variant is None:
        raise ValidationError("Wybierz produkt z katalogu.")
    if not isinstance(lines, list) or len(lines) > 40:
        raise ValidationError("Receptura może mieć do 40 składników.")
    cleaned = []
    seen = set()
    for line in lines:
        if not isinstance(line, dict):
            raise ValidationError("Niepoprawny składnik receptury.")
        stock = StockItem.objects.filter(pk=line.get("stock_id")).first()
        if stock is None or stock.variant_id:
            raise ValidationError(
                "Składnik musi być surowcem, opakowaniem albo inną pozycją magazynową."
            )
        if stock.pk in seen:
            raise ValidationError(f"{stock.name} jest na recepturze więcej niż raz.")
        seen.add(stock.pk)
        quantity = decimal(line.get("quantity"), stock.name, positive=True)
        if stock.unit == "szt" and quantity != int(quantity):
            raise ValidationError(
                f"{stock.name}: na jedno opakowanie podaj całe sztuki."
            )
        cleaned.append((stock, quantity))
    recipe = Recipe.objects.filter(variant=variant).first()
    if not cleaned:
        if recipe:
            recipe.delete()
        return None
    if recipe is None:
        recipe = Recipe.objects.create(variant=variant)
    recipe.lines.all().delete()
    RecipeLine.objects.bulk_create(
        [
            RecipeLine(recipe=recipe, stock=stock, quantity=quantity)
            for stock, quantity in cleaned
        ]
    )
    return recipe


def consume_recipe(variant, units, user, report):
    recipe = Recipe.objects.filter(variant=variant).first()
    if recipe is None:
        return
    lines = list(recipe.lines.select_related("stock").order_by("stock_id", "id"))
    if not lines:
        return
    locked = {
        row.pk: row
        for row in StockItem.objects.select_for_update()
        .filter(pk__in=[line.stock_id for line in lines])
        .order_by("pk")
    }
    for line in lines:
        need = (line.quantity * units).quantize(Decimal("0.001"))
        stock = locked[line.stock_id]
        free = stock.quantity - stock.reserved
        if free < need:
            raise ValidationError(
                f"Za mało surowca: {stock.name}. Na {units} opak. potrzeba {need} {stock.unit}, dostępne {free} {stock.unit}."
            )
        record_move(
            stock, -need, 0, user, f"Zużycie receptury · {variant.name}", report
        )


def supplier_rows():
    return Supplier.objects.filter(active=True).order_by("name")


def recipe_rows():
    rows = {}
    for recipe in Recipe.objects.prefetch_related("lines"):
        rows[recipe.variant_id] = [
            {"stock_id": line.stock_id, "quantity": str(line.quantity)}
            for line in recipe.lines.all()
        ]
    return rows


def add_stock_product(category_id, name, unit, supplier_id=None):
    category = StockCategory.objects.filter(pk=category_id).first()
    if category is None:
        raise ValidationError("Wybierz kategorię.")
    if category.system:
        raise ValidationError(
            "Produkty do sprzedaży dodajesz w katalogu. W magazynie pojawią się same."
        )
    if unit not in ("szt", "kg"):
        raise ValidationError("Jednostka to szt albo kg.")
    cleaned = " ".join(str(name or "").split())
    if not cleaned or len(cleaned) > 180:
        raise ValidationError("Podaj nazwę produktu.")
    return StockItem.objects.create(
        code=stock_code(cleaned),
        name=cleaned,
        group="custom",
        unit=unit,
        category=category,
        supplier=supplier_or_none(supplier_id),
    )


def receive_stock(stock_id, quantity, user, why):
    stock = StockItem.objects.select_for_update().get(pk=stock_id)
    if stock.unit == "szt":
        number = integer(quantity, "Liczba sztuk")
    else:
        number = decimal(quantity, "Ilość", True)
    record_move(stock, number, 0, user, "Przyjęcie towaru: " + why)
    assign_stock(stock, user)
    return stock


def set_stock_quantity(item_id, quantity, user, why):
    stock = StockItem.objects.select_for_update().get(pk=item_id)
    if stock.unit == "szt":
        number = decimal(quantity, "Liczba sztuk")
        if number != int(number) or number > 10000000:
            raise ValidationError(
                "Liczba sztuk: podaj liczbę całkowitą od 0 do 10 000 000."
            )
        quantity = number
    else:
        quantity = decimal(quantity, "Ilość")
    if quantity < stock.reserved:
        raise ValidationError(
            "Stan nie może być mniejszy niż ilość zarezerwowana dla zamówień."
        )
    increased = quantity > stock.quantity
    record_move(stock, quantity - stock.quantity, 0, user, why)
    if increased:
        assign_stock(stock, user)
    return stock


def annotated_orders(user):
    order_q, _space = workspace_filter(user)
    items = Item.objects.filter(order=OuterRef("pk"))
    return Order.objects.filter(order_q).annotate(
        has_item=Exists(items),
        unfinished=Exists(items.filter(packed__lt=F("quantity"))),
        needs_production=Exists(
            items.filter(quantity__gt=F("allocated") + F("produced"))
        ),
        item_quantity=Sum("items__quantity"),
        item_packed=Sum("items__packed"),
        item_allocated=Sum("items__allocated"),
        item_produced=Sum("items__produced"),
    )


def status_filter_q(name):
    closed = Q(cancelled_at__isnull=True, issued_at__isnull=True)
    confirmed = closed & Q(confirmed_at__isnull=False)
    if name == "cancelled":
        return Q(cancelled_at__isnull=False)
    if name == "issued":
        return Q(cancelled_at__isnull=True, issued_at__isnull=False)
    if name == "draft":
        return closed & Q(confirmed_at__isnull=True)
    if name == "completed":
        return confirmed & Q(has_item=True, unfinished=False)
    if name == "producing":
        return confirmed & Q(needs_production=True)
    if name == "awaiting_shipment":
        return confirmed & Q(needs_production=False) & (Q(unfinished=True) | Q(has_item=False))
    if name == "late":
        return (status_filter_q("producing") | status_filter_q("awaiting_shipment")) & Q(
            due_at__lt=timezone.now()
        )
    return Q()


def order_summary_from_query(qs):
    active_q = status_filter_q("producing") | status_filter_q("awaiting_shipment")
    active_ids = qs.filter(active_q).values("pk")
    totals = Item.objects.filter(order_id__in=active_ids).aggregate(
        production=Sum(F("quantity") - F("allocated") - F("produced")),
        packing=Sum(F("quantity") - F("packed")),
    )
    return {
        "orders": qs.values("pk").distinct().count(),
        "active": qs.filter(active_q).values("pk").distinct().count(),
        "overdue": qs.filter(active_q, due_at__lt=timezone.now()).values("pk").distinct().count(),
        "production_remaining": int(totals["production"] or 0),
        "packing_remaining": int(totals["packing"] or 0),
    }


def load_order_page(ids):
    if not ids:
        return []
    found = {
        order.pk: order
        for order in Order.objects.select_related("customer")
        .prefetch_related("items__labels", "tasks")
        .filter(pk__in=ids)
    }
    return [found[pk] for pk in ids if pk in found]


def select_orders(user, params):
    """One database page, with totals for the whole workspace."""
    qs = annotated_orders(user)
    summary = order_summary_from_query(qs)
    scope = params.get("orders_scope") or "page"
    if scope == "none":
        return [], summary, {"limit": 0, "offset": 0, "count": summary["orders"]}
    if scope == "upcoming":
        active_q = status_filter_q("producing") | status_filter_q("awaiting_shipment")
        upcoming = qs.filter(active_q).order_by(F("due_at").asc(nulls_last=True), "id")
        ids = list(upcoming.values_list("pk", flat=True)[:6])
        return load_order_page(ids), summary, {
            "limit": 6,
            "offset": 0,
            "count": upcoming.count(),
        }
    text = str(params.get("orders_q") or "").strip()
    status_name = str(params.get("orders_status") or "all")
    if status_name not in ("", "all"):
        qs = qs.filter(status_filter_q(status_name))
    if text:
        qs = qs.filter(
            Q(customer__name__icontains=text) | Q(items__name__icontains=text)
        ).distinct()
    key = params.get("orders_sort") or ""
    direction = "desc" if params.get("orders_dir") == "desc" else "asc"
    if key == "due":
        ordering = [F("due_at").desc(nulls_last=True) if direction == "desc" else F("due_at").asc(nulls_last=True), "id"]
    elif key == "customer":
        ordering = ["-customer__name" if direction == "desc" else "customer__name", "id"]
    elif key == "progress":
        sign = "-" if direction == "desc" else ""
        qs = qs.annotate(
            progress=Case(
                When(item_quantity__gt=0, then=F("item_packed") * 1000 / F("item_quantity")),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        ordering = [f"{sign}progress", "id"]
    elif key == "status":
        qs = qs.annotate(
            status_rank=Case(
                When(cancelled_at__isnull=False, then=Value(5)),
                When(issued_at__isnull=False, then=Value(4)),
                When(confirmed_at__isnull=True, then=Value(0)),
                When(needs_production=True, then=Value(1)),
                When(unfinished=False, has_item=True, then=Value(3)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        ordering = ["-status_rank" if direction == "desc" else "status_rank", "id"]
    elif key == "flavor":
        flavor = Item.objects.filter(order=OuterRef("pk")).order_by("id").values("product_name")[:1]
        qs = qs.annotate(flavor_name=Subquery(flavor))
        ordering = ["-flavor_name" if direction == "desc" else "flavor_name", "id"]
    else:
        ordering = ["-id"]
    try:
        limit = min(100, max(1, int(params.get("orders_limit") or 50)))
        offset = max(0, int(params.get("orders_offset") or 0))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    count = qs.count()
    ids = list(qs.order_by(*ordering).values_list("pk", flat=True)[offset:offset + limit])
    return load_order_page(ids), summary, {
        "limit": limit,
        "offset": offset,
        "count": count,
    }
