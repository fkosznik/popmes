"""Business operations. Call under transaction.atomic with the order row locked."""

from decimal import Decimal, InvalidOperation
from django.db.models import Max, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import (
    Item,
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
    return item.labels.order_by("-version").first()


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
    sync_catalog_stock()
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
    if units > to_produce(item):
        raise ValidationError(
            "Liczba przekracza pozostałe opakowania do wyprodukowania."
        )
    report = Report.objects.create(
        task=task,
        user=user,
        units=units,
        label=approved_label(item),
        note=str(data.get("note", ""))[:4000],
    )
    item.produced += units
    item.save(update_fields=["produced"])
    adjust_variant(
        item.variant, units, units, user, "Produkcja opakowań", report
    )
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
    report = Report.objects.create(
        task=task,
        user=user,
        units=units,
        label=approved_label(item),
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
    adjust_variant(
        item.variant, -units, -units, user, "Wysłano", report
    )
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
            label=approved_label(item),
            note=note,
        )
        ShipmentLine.objects.create(
            shipment=shipment, item=item, units=units, report=report
        )
        item.packed += units
        item.save(update_fields=["packed"])
        adjust_variant(item.variant, -units, -units, user, "Wysłano", report)
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
            if item.allocated + item.produced - report.units < item.packed:
                raise ValidationError(
                    "Najpierw cofnij wysyłkę tych opakowań."
                )
            item.produced -= report.units
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
        touched.append(item.variant)
    for variant in touched:
        assign_available(variant, user)
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
        StockItem.objects.update_or_create(
            code=f"POP-{variant.sku}",
            defaults={
                "name": f"{variant.name} · {grams_label(variant.weight_g)} g",
                "group": "popcorn",
                "unit": "szt",
                "position": int(variant.weight_g),
                "variant": variant,
            },
        )


def finished_category():
    category, _ = StockCategory.objects.get_or_create(
        system=True, defaults={"name": "Produkty", "position": 0}
    )
    return category


def sync_catalog_stock():
    category = finished_category()
    for variant in Variant.objects.select_related("product"):
        StockItem.objects.update_or_create(
            variant=variant,
            defaults={
                "code": f"POP-{variant.sku}"[:40],
                "name": f"{variant.name} · {grams_label(variant.weight_g)} g",
                "group": "popcorn",
                "unit": "szt",
                "position": int(variant.weight_g),
                "category": category,
            },
        )


def record_move(stock, quantity_delta, reserved_delta, user, reason, report=None):
    stock.quantity += Decimal(quantity_delta)
    stock.reserved += Decimal(reserved_delta)
    if stock.reserved < 0:
        raise ValidationError("Rezerwacja magazynu spadłaby poniżej zera.")
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
    sync_catalog_stock()
    return StockItem.objects.select_for_update().get(variant=variant)


def adjust_variant(variant, quantity_delta, reserved_delta, user, reason, report=None):
    stock = variant_stock_locked(variant)
    record_move(stock, quantity_delta, reserved_delta, user, reason, report)
    return stock


def allocate_item(item, user, order):
    stock = variant_stock_locked(item.variant)
    free = stock.quantity - stock.reserved
    take = min(to_produce(item), int(free)) if free > 0 else 0
    if take <= 0:
        return 0
    item.allocated += take
    item.save(update_fields=["allocated"])
    record_move(stock, 0, take, user, f"Rezerwacja do {order.number}")
    return take


def assign_available(variant, user):
    stock = variant_stock_locked(variant)
    order_ids = list(
        Item.objects.filter(
            variant=variant,
            order__confirmed_at__isnull=False,
            order__cancelled_at__isnull=True,
            order__issued_at__isnull=True,
        )
        .values_list("order_id", flat=True)
        .distinct()
    )
    if not order_ids:
        return
    locked_ids = list(
        Order.objects.select_for_update(skip_locked=True)
        .filter(pk__in=order_ids)
        .order_by("id")
        .values_list("pk", flat=True)
    )
    items = Item.objects.select_for_update().filter(
        variant=variant, order_id__in=locked_ids
    ).select_related("order").order_by("-order__priority", "order__due_at", "id")
    for item in items:
        need = to_produce(item)
        free = stock.quantity - stock.reserved
        take = min(need, int(free)) if free > 0 else 0
        if take <= 0:
            if free <= 0:
                break
            continue
        item.allocated += take
        item.save(update_fields=["allocated"])
        record_move(stock, 0, take, user, f"Rezerwacja do {item.order.number}")
        refresh_completion(item.order)


def release_covered(item, units, user, why):
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


def release_unshipped(order, user, why):
    variants = []
    for item in order.items.select_related("variant").order_by("variant_id", "id"):
        held = ready_to_ship(item)
        if held <= 0:
            continue
        stock = variant_stock_locked(item.variant)
        record_move(stock, 0, -held, user, why)
        variants.append(item.variant)
    for variant in variants:
        assign_available(variant, user)


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
    sync_catalog_stock()
    return StockItem.objects.select_related("category", "supplier").order_by(
        "category__position", "position", "name"
    )


def category_rows():
    sync_catalog_stock()
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
    if stock.variant_id:
        assign_available(stock.variant, user)
    return stock


def set_stock_quantity(item_id, quantity, user, why):
    sync_catalog_stock()
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
    if increased and stock.variant_id:
        assign_available(stock.variant, user)
    return stock
