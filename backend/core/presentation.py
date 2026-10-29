from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from .models import Batch, Workspace
from .services import (
    status,
    roles,
    available,
    blockers,
    task_status,
    deficits,
)


def organization_data(org):
    return {
        "name": org.name,
        "default_language": org.default_language,
        "theme": org.theme,
    }


def workspace_data(space):
    return {
        "id": space.pk,
        "name": space.name,
        "active": space.active,
        "primary": space.primary,
    }


def workspaces_data():
    return [workspace_data(space) for space in Workspace.objects.order_by("id")]


def user_data(user):
    # Reading the session must not insert a profile. The account form creates it on save.
    try:
        profile = user.profile
    except ObjectDoesNotExist:
        profile = None
    appearance = profile.appearance if profile else "light"
    return {
        "id": user.pk,
        "username": user.username,
        "name": user.first_name or user.username,
        "email": user.email,
        "phone": profile.phone if profile else "",
        "street": profile.street if profile else "",
        "postal_code": profile.postal_code if profile else "",
        "city": profile.city if profile else "",
        "country": profile.country if profile else "Polska",
        "language": profile.language if profile else "pl",
        "timezone": profile.timezone if profile else "Europe/Warsaw",
        "start_page": profile.start_page if profile else "dashboard",
        "orders_filter": profile.orders_filter if profile else "all",
        "appearance": appearance if appearance == "dark" else "light",
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


def ordered_labels(item):
    labels = list(item.labels.all())
    labels.sort(key=lambda label: label.version, reverse=True)
    return labels


def item_data(item):
    labels = ordered_labels(item)
    return {
        "id": item.pk,
        "variant_id": item.variant_id,
        "product_id": item.product_id,
        "name": item.name,
        "product_name": item.product_name,
        "weight_g": str(item.weight_g),
        "quantity": item.quantity,
        "produced": item.produced,
        "allocated": item.allocated,
        "packed": item.packed,
        "packaging": item.packaging,
        "instruction": item.instruction,
        "custom_label": item.custom_label,
        "label": label_data(labels[0] if labels else None),
        "labels": [label_data(label) for label in labels],
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
    customer = order_customer(task.order)
    if task.item_id:
        result["item"] = item_data(task.item)
        result["customer_name"] = customer.get("name", "")
    if task.kind in ("shipping", "packing"):
        result["address"] = task.order.address
        result["delivery"] = task.order.delivery
        result["customer_name"] = customer.get("name", "")
        result["customer_email"] = customer.get("email", "")
        result["customer_phone"] = customer.get("phone", "")
        result["items"] = [item_data(item) for item in task.order.items.all()]
    result["batches"] = [
        batch_data(b)
        for b in Batch.objects.filter(
            order=task.order, product_id=task.product_id
        ).select_related("origin")
    ]
    return result


def category_data(category):
    return {
        "id": category.pk,
        "name": category.name,
        "system": category.system,
        "position": category.position,
    }


def stock_data(item):
    available = item.quantity - item.reserved
    return {
        "id": item.pk,
        "code": item.code,
        "name": item.name,
        "group": item.group,
        "unit": item.unit,
        "quantity": str(item.quantity),
        "reserved": str(item.reserved),
        "available": str(available),
        "category_id": item.category_id,
        "variant_id": item.variant_id,
        "artwork_sha256": item.artwork_sha256,
        "artwork_version": item.artwork_version,
        "artwork_unknown": item.artwork_unknown,
        "supplier_id": item.supplier_id,
        "supplier_name": item.supplier.name if item.supplier_id else "",
        "weight_g": str(item.variant.weight_g) if item.variant_id else None,
        "archived": item.archived,
    }


def stock_profile(item):
    data = stock_data(item)
    data["moves"] = [
        {
            "id": move.pk,
            "delta": str(move.delta),
            "quantity_after": str(move.quantity_after),
            "reason": move.reason,
            "user": move.user.first_name or move.user.username,
            "created_at": move.created_at,
        }
        for move in item.moves.select_related("user").order_by("-id")[:25]
    ]
    data["used_in"] = [
        {
            "variant_id": line.recipe.variant_id,
            "name": line.recipe.variant.name,
            "quantity": str(line.quantity),
        }
        for line in item.recipe_lines.select_related("recipe__variant")
    ]
    if item.variant_id:
        variant = item.variant
        data["variant"] = {
            "id": variant.pk,
            "sku": variant.sku,
            "name": variant.name,
            "weight_g": str(variant.weight_g),
            "packaging": variant.packaging,
            "custom_label": variant.custom_label,
            "instruction": variant.instruction,
            "product_id": variant.product_id,
            "product_name": variant.product.name,
        }
    else:
        data["variant"] = None
    data["supplier"] = supplier_data(item.supplier) if item.supplier_id else None
    return data


def supplier_data(supplier):
    return {
        "id": supplier.pk,
        "name": supplier.name,
        "contact": supplier.contact,
        "email": supplier.email,
        "phone": supplier.phone,
        "active": supplier.active,
    }


def shipment_number(report):
    try:
        return report.shipment_line.shipment.number
    except ObjectDoesNotExist:
        return None


def shipment_data(shipment):
    return {
        "id": shipment.pk,
        "number": shipment.number,
        "address": shipment.address,
        "note": shipment.note,
        "created_at": shipment.created_at,
        "lines": [
            {"item_id": line.item_id, "name": line.item.name, "units": line.units}
            for line in shipment.lines.select_related("item")
        ],
    }


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
        "shipment": shipment_number(report),
        "allocations": [
            {"batch": m.batch.number, "grams": str(-m.delta_g)}
            for m in report.movements.select_related("batch")
            if m.delta_g < 0
        ],
    }


def order_customer(order):
    customer = dict(order.customer_snapshot or {})
    live = order.customer
    if live:
        for field in ("name", "contact", "email", "phone", "tax_id", "address"):
            if not str(customer.get(field) or "").strip():
                customer[field] = getattr(live, field) or ""
    return customer


def order_data(order):
    items = list(order.items.all())
    tasks = list(order.tasks.all())
    customer = order_customer(order)
    return {
        "id": order.pk,
        "number": order.number,
        "customer_id": order.customer_id,
        "customer_name": customer.get("name") or "Bez klienta",
        "customer": customer,
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
        "produced": sum(i.produced for i in items),
        "allocated": sum(i.allocated for i in items),
        "packed": sum(i.packed for i in items),
        "target_g": str(sum(t.target_g for t in tasks if t.kind == "production")),
        "produced_g": str(sum(t.produced_g for t in tasks if t.kind == "production")),
        "deficits": deficits(order) if order.confirmed_at else [],
        "completed_at": order.completed_at,
        "issued_at": order.issued_at,
    }
