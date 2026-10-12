from django.utils import timezone
from .models import Batch
from .services import (
    status,
    roles,
    available,
    latest_label,
    blockers,
    task_status,
    deficits,
)


def user_data(user):
    return {
        "id": user.pk,
        "username": user.username,
        "name": user.first_name or user.username,
        "roles": roles(user),
        "active": user.is_active,
    }


def label_data(label):
    if not label:
        return None
    return {
        "id": label.pk,
        "version": label.version,
        "filename": label.filename,
        "approved": bool(label.approved_at),
        "url": f"/api/labels/{label.pk}/download/",
    }


def batch_data(batch):
    return {
        "id": batch.pk,
        "number": batch.number,
        "order_id": batch.order_id,
        "origin_order_id": batch.origin.order_id,
        "origin_task_id": batch.origin_id,
        "product_id": batch.product_id,
        "product_name": batch.origin.product_name,
        "available_g": str(batch.available_g),
        "created_at": batch.created_at.isoformat(),
    }


def item_data(item):
    return {
        "id": item.pk,
        "variant_id": item.variant_id,
        "product_id": item.product_id,
        "name": item.name,
        "product_name": item.product_name,
        "weight_g": str(item.weight_g),
        "quantity": item.quantity,
        "packed": item.packed,
        "packaging": item.packaging,
        "instruction": item.instruction,
        "custom_label": item.custom_label,
        "label": label_data(latest_label(item)),
        "labels": [label_data(l) for l in item.labels.order_by("-version")],
    }


def task_data(task, user):
    sessions = list(task.sessions.select_related("user"))
    seconds = sum(
        ((s.ended_at or timezone.now()) - s.started_at).total_seconds()
        for s in sessions
    )
    own_active = any(s.user_id == user.pk and not s.ended_at for s in sessions)
    result = {
        "id": task.pk,
        "order_id": task.order_id,
        "order_number": task.order.number,
        "kind": task.kind,
        "product_id": task.product_id,
        "product_name": task.product_name,
        "color": task.product.color,
        "target_g": str(task.target_g),
        "produced_g": str(task.produced_g),
        "instruction": task.instruction,
        "notes": task.order.production_notes
        if task.kind == "production"
        else task.order.packing_notes,
        "due_at": task.order.due_at,
        "priority": task.order.priority,
        "hold_reason": task.hold_reason,
        "blockers": blockers(task),
        "status": task_status(task),
        "active": own_active,
        "workers": [
            s.user.first_name or s.user.username for s in sessions if not s.ended_at
        ],
        "work_seconds": round(seconds),
        "supplemental": task.supplemental,
        "available_g": str(available(task.order, task.product_id)),
    }
    if task.kind == "packing":
        result["item"] = item_data(task.item)
        result["customer_name"] = task.order.customer_snapshot.get("name", "")
    result["batches"] = [
        batch_data(b)
        for b in Batch.objects.filter(
            order=task.order, product_id=task.product_id
        ).select_related("origin")
    ]
    return result


def report_data(report):
    return {
        "id": report.pk,
        "task_id": report.task_id,
        "kind": report.task.kind,
        "product_name": report.task.product_name,
        "user": report.user.first_name or report.user.username,
        "created_at": report.created_at,
        "grams": str(report.grams),
        "waste_g": str(report.waste_g),
        "units": report.units,
        "note": report.note,
        "measured": report.measured,
        "corrected": hasattr(report, "correction"),
        "label": label_data(report.label),
        "batch": report.batch.number if report.batch_id else None,
        "allocations": [
            {"batch": m.batch.number, "grams": str(-m.delta_g)}
            for m in report.movements.select_related("batch")
            if m.delta_g < 0
        ],
    }


def order_data(order):
    items = list(order.items.all())
    tasks = list(order.tasks.all())
    return {
        "id": order.pk,
        "number": order.number,
        "customer_id": order.customer_id,
        "customer_name": order.customer_snapshot.get("name")
        or (order.customer.name if order.customer else "Bez klienta"),
        "customer": order.customer_snapshot,
        "created_at": order.created_at,
        "due_at": order.due_at,
        "priority": order.priority,
        "delivery": order.delivery,
        "address": order.address,
        "delivery_address_id": order.delivery_address_id,
        "status": status(order),
        "hold_reason": order.hold_reason,
        "version": order.version,
        "production_notes": order.production_notes,
        "packing_notes": order.packing_notes,
        "internal_notes": order.internal_notes,
        "items": [item_data(i) for i in items],
        "units": sum(i.quantity for i in items),
        "packed": sum(i.packed for i in items),
        "target_g": str(sum(t.target_g for t in tasks if t.kind == "production")),
        "produced_g": str(sum(t.produced_g for t in tasks if t.kind == "production")),
        "deficits": deficits(order) if order.confirmed_at else [],
        "completed_at": order.completed_at,
        "issued_at": order.issued_at,
    }
