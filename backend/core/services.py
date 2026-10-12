"""Business operations. Call under transaction.atomic with the order row locked."""

from decimal import Decimal, InvalidOperation
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import (
    Product,
    Task,
    Batch,
    Report,
    Movement,
    Correction,
    WorkSession,
    Event,
)

ROLES = ["sales", "production", "packing", "manager", "admin"]
ZERO = Decimal("0")


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


def status(order):
    if order.cancelled_at:
        return "cancelled"
    if order.issued_at:
        return "issued"
    if not order.confirmed_at:
        return "draft"
    items = list(order.items.all())
    if items and all(i.packed >= i.quantity for i in items):
        return "completed"
    if order.tasks.filter(started_at__isnull=False).exists() or any(
        i.packed for i in items
    ):
        return "in_progress"
    return "queued"


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


def complete(task):
    return (
        task.produced_g >= task.target_g
        if task.kind == "production"
        else task.item.packed >= task.item.quantity
    )


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
    if task.kind == "packing" and not complete(task):
        if not label_ready(task.item):
            values.append("Etykieta wymaga zatwierdzenia")
        if available(task.order, task.product_id) < task.item.weight_g:
            values.append("Oczekiwanie na popcorn")
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
    if order.delivery == "courier" and not order.address.strip():
        raise ValidationError("Dla kuriera podaj adres dostawy.")
    targets = {}
    for item in order.items.select_related("variant__product"):
        variant = item.variant
        if not variant.active or not variant.product.active:
            raise ValidationError(f"Produkt {variant.name} jest nieaktywny.")
        snapshot_item(item, variant)
        item.save()
        targets[item.product_id] = (
            targets.get(item.product_id, ZERO) + item.quantity * item.weight_g
        )
        Task.objects.create(
            order=order,
            kind="packing",
            product=item.product,
            product_name=item.product_name,
            item=item,
            instruction=item.instruction,
        )
    lock_products(targets)
    for product_id, grams in sorted(targets.items()):
        grams -= reserve_stock(order, product_id, grams, user)
        variant = order.items.filter(product_id=product_id).first().variant
        Task.objects.create(
            order=order,
            kind="production",
            product_id=product_id,
            product_name=variant.product.name,
            instruction=variant.product.instruction,
            target_g=grams,
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


def production_report(task, user, data):
    ensure_task(task)
    lock_products(task.order.items.values_list("product_id", flat=True))
    grams = decimal(data.get("grams"), positive=True)
    waste = decimal(data.get("waste_g", 0))
    if data.get("batch_id"):
        batch = (
            Batch.objects.select_for_update()
            .filter(pk=data["batch_id"], origin=task, order=task.order)
            .first()
        )
        if not batch:
            raise ValidationError("Partia nie należy do tego zlecenia.")
    else:
        batch = Batch.objects.create(
            origin=task, order=task.order, product=task.product
        )
    report = Report.objects.create(
        task=task,
        user=user,
        grams=grams,
        waste_g=waste,
        batch=batch,
        note=str(data.get("note", ""))[:4000],
    )
    movement(batch, task.order, user, grams, "Produkcja", report)
    task.produced_g += grams
    task.started_at = task.started_at or timezone.now()
    task.save()
    refresh_completion(task.order)
    release_surplus(task.order, user)
    event(
        task.order,
        user,
        "Zgłoszono produkcję",
        report_id=report.pk,
        batch=batch.number,
        grams=str(grams),
        waste_g=str(waste),
    )
    return report


def packing_report(task, user, data):
    ensure_task(task)
    item = task.item
    units = integer(data.get("units"))
    if units > item.quantity - item.packed:
        raise ValidationError("Liczba przekracza pozostałe sztuki do zapakowania.")
    nominal = units * item.weight_g
    measured = data.get("grams") not in [None, ""]
    grams = decimal(data["grams"], positive=True) if measured else nominal
    waste = decimal(data.get("waste_g", 0))
    if grams < nominal + waste:
        raise ValidationError(
            "Łączne zużycie musi pokrywać masę netto sztuk oraz podane straty."
        )
    batches = list(
        Batch.objects.select_for_update()
        .filter(order=task.order, product=task.product, available_g__gt=0)
        .order_by("created_at", "id")
    )
    chosen = data.get("allocations")
    allocations = []
    if chosen:
        pool = {b.pk: b for b in batches}
        seen = set()
        for entry in chosen:
            bid = int(entry["batch_id"])
            amount = decimal(entry["grams"], positive=True)
            if bid in seen or bid not in pool or pool[bid].available_g < amount:
                raise ValidationError(
                    "Niepoprawny wybór partii lub niewystarczająca masa."
                )
            seen.add(bid)
            allocations.append((pool[bid], amount))
        if sum((amount for _, amount in allocations), ZERO) != grams:
            raise ValidationError("Suma pobrań z partii musi odpowiadać zużyciu.")
    else:
        remaining = grams
        for batch in batches:
            amount = min(remaining, batch.available_g)
            if amount:
                allocations.append((batch, amount))
            remaining -= amount
        if remaining > 0:
            raise ValidationError("Za mało popcornu w dostępnych partiach.")
    report = Report.objects.create(
        task=task,
        user=user,
        grams=grams,
        units=units,
        waste_g=waste,
        measured=measured,
        label=latest_label(item),
        note=str(data.get("note", ""))[:4000],
    )
    for batch, amount in allocations:
        movement(batch, task.order, user, -amount, "Pakowanie", report)
    item.packed += units
    item.save(update_fields=["packed"])
    task.started_at = task.started_at or timezone.now()
    task.save(update_fields=["started_at"])
    refresh_completion(task.order)
    event(
        task.order,
        user,
        "Zgłoszono pakowanie",
        report_id=report.pk,
        units=units,
        grams=str(grams),
        label_version=report.label.version if report.label else None,
    )
    return report


def deficits(order):
    result = []
    for product_id in order.items.values_list("product_id", flat=True).distinct():
        needed = sum(
            (
                (i.quantity - i.packed) * i.weight_g
                for i in order.items.filter(product_id=product_id)
            ),
            ZERO,
        )
        stock = available(order, product_id)
        planned = sum(
            (
                max(ZERO, t.target_g - t.produced_g)
                for t in order.tasks.filter(kind="production", product_id=product_id)
            ),
            ZERO,
        )
        result.append(
            {
                "product_id": product_id,
                "needed_g": str(needed),
                "available_g": str(stock),
                "planned_g": str(planned),
                "shortage_g": str(max(ZERO, needed - stock - planned)),
            }
        )
    return result


def replenish(order, user):
    ensure_open(order)
    if not order.confirmed_at:
        raise ValidationError("Najpierw zatwierdź zamówienie.")
    created = []
    for d in deficits(order):
        grams = Decimal(d["shortage_g"])
        if grams > 0:
            base = order.tasks.filter(
                kind="production", product_id=d["product_id"]
            ).first()
            task = Task.objects.create(
                order=order,
                kind="production",
                product=base.product,
                product_name=base.product_name,
                instruction=base.instruction,
                target_g=grams,
                supplemental=True,
            )
            created.append(task.pk)
    event(order, user, "Uzupełniono plan produkcji", tasks=created)


def reverse_report(report, user, data):
    task = report.task
    order = task.order
    ensure_open(order)
    if hasattr(report, "correction"):
        raise ValidationError("Raport został już skorygowany.")
    why = reason(data)
    restore = data.get("restore_mass") is True
    if task.kind == "production":
        batch = Batch.objects.select_for_update().get(pk=report.batch_id)
        if batch.order_id != order.pk:
            raise ValidationError(
                "Partia została przeniesiona. Najpierw rozlicz transfer."
            )
        movement(batch, order, user, -report.grams, "Korekta produkcji: " + why)
        task.produced_g -= report.grams
        task.save(update_fields=["produced_g"])
    else:
        task.item.packed -= report.units
        task.item.save(update_fields=["packed"])
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
    for change in data.get("items", []):
        item = order.items.filter(pk=change.get("id")).first()
        if not item:
            raise ValidationError("Pozycja nie należy do zamówienia.")
        qty = integer(change.get("quantity"))
        if qty < item.packed:
            raise ValidationError("Najpierw rozlicz już zapakowane sztuki.")
        item.quantity = qty
        item.save(update_fields=["quantity"])
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
    if order.confirmed_at:
        # Keep historical production; resize outstanding targets for each flavor.
        for product_id in order.items.values_list("product_id", flat=True).distinct():
            tasks = list(
                order.tasks.filter(kind="production", product_id=product_id).order_by(
                    "id"
                )
            )
            needed = sum(
                (
                    (i.quantity - i.packed) * i.weight_g
                    for i in order.items.filter(product_id=product_id)
                ),
                ZERO,
            )
            outstanding = max(ZERO, needed - available(order, product_id))
            for index, task in enumerate(tasks):
                task.target_g = task.produced_g + (outstanding if index == 0 else ZERO)
                task.save(update_fields=["target_g"])
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
