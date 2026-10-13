import hashlib
import io
import json
import uuid
from datetime import timedelta
from functools import wraps
from pathlib import Path
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction, connection, IntegrityError
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.fields import DateTimeField
from rest_framework.throttling import BaseThrottle
from PIL import Image
from pypdf import PdfReader
from ..models import (
    Product,
    Variant,
    Customer,
    Order,
    Item,
    Task,
    Batch,
    Report,
    Label,
    LoginAttempt,
    RequestReceipt,
    Profile,
    StockItem,
    Supplier,
    Workspace,
)
from django.db.models import Max
from ..serializers import ProductSerializer, VariantSerializer, CustomerSerializer
from .. import services as s
from ..presentation import (
    user_data,
    task_data,
    order_data,
    report_data,
    batch_data,
    shipment_data,
    stock_data,
    stock_profile,
    category_data,
    supplier_data,
    organization_data,
    workspaces_data,
)


from core.views.auth import locked_order, mutation

@api_view(["POST"])
@mutation
def save_order(request):
    s.permit(request.user, "sales", "manager")
    data = request.data
    if "payload" in data:
        try:
            data = json.loads(data["payload"])
        except (ValueError, TypeError):
            raise ValidationError("Niepoprawny formularz zamówienia.")
    if not isinstance(data, dict):
        raise ValidationError("Niepoprawny formularz zamówienia.")
    uploads = {}
    for index, entry in enumerate(data.get("items", [])):
        upload = request.FILES.get(f"label_{index}")
        if upload:
            uploads[index] = (upload, *validate_file(upload))
    if data.get("id"):
        order = locked_order(data["id"])
        if order.confirmed_at or order.cancelled_at:
            raise ValidationError(
                "Zatwierdzone zamówienie edytuj przez zmianę zamówienia."
            )
        if int(data.get("version", -1)) != order.version:
            raise ValidationError("Zamówienie zmieniło się. Odśwież dane.")
        if Label.objects.filter(item__order=order).exists():
            raise ValidationError(
                "Szkic z etykietami: zatwierdź go i użyj zmiany ilości. Historia etykiet jest zachowywana."
            )
        order.items.all().delete()
    else:
        order = Order.objects.create(
            created_by=request.user,
            workspace=s.current_workspace(request.user),
        )
    if data.get("customer_id"):
        order.customer = get_object_or_404(
            Customer, pk=data["customer_id"], active=True
        )
    else:
        order.customer = None
    order.due_at = (
        DateTimeField().run_validation(data["due_at"]) if data.get("due_at") else None
    )
    if data.get("priority", "normal") not in ["normal", "urgent"] or data.get(
        "delivery", "courier"
    ) not in ["pickup", "courier", "locker", "other"]:
        raise ValidationError("Niepoprawny priorytet lub sposób odbioru.")
    for field in [
        "priority",
        "delivery",
        "address",
        "production_notes",
        "packing_notes",
        "internal_notes",
    ]:
        if field in data:
            setattr(order, field, str(data[field])[:4000])
    address_id = str(data.get("delivery_address_id", ""))
    if address_id:
        addresses = order.customer.delivery_addresses if order.customer else []
        address = next((a for a in addresses if a["id"] == address_id), None)
        if not address:
            raise ValidationError("Wybierz adres należący do wybranego klienta.")
        order.address = address["name"] + "\n" + address["address"]
    elif order.delivery in ("courier", "locker"):
        raise ValidationError(
            "Dla paczkomatu wybierz zapisany punkt odbioru."
            if order.delivery == "locker"
            else "Wybierz zapisany adres dostawy klienta."
        )
    else:
        order.address = ""
    order.delivery_address_id = address_id
    order.save()
    for index, entry in enumerate(data.get("items", [])):
        variant = get_object_or_404(
            Variant.objects.select_related("product"),
            pk=entry["variant_id"],
            active=True,
            product__active=True,
        )
        item = Item(order=order, variant=variant, quantity=s.integer(entry["quantity"]))
        s.snapshot_item(item, variant)
        item.save()
        if index in uploads:
            upload, mime, digest = uploads[index]
            Label.objects.create(
                item=item,
                version=1,
                file=upload,
                filename=Path(upload.name).name[:200],
                mime=mime,
                content_sha256=digest,
                uploaded_by=request.user,
            )
    s.event(order, request.user, "Zapisano szkic")
    if data.get("confirm") is True:
        s.confirm(order, request.user)
    return {"id": order.pk}



@api_view(["GET"])
def detail(request, pk):
    s.permit(request.user, "sales", "manager", "packing")
    order = get_object_or_404(Order, pk=pk)
    result = order_data(order)
    result["events"] = [
        {
            "id": e.pk,
            "action": e.action,
            "detail": e.detail,
            "user": e.user.first_name or e.user.username,
            "created_at": e.created_at,
        }
        for e in order.events.select_related("user").order_by("-id")
    ]
    result["reports"] = [
        report_data(r)
        for r in Report.objects.filter(task__order=order)
        .select_related("task", "user", "label", "batch", "shipment_line__shipment")
        .order_by("-id")
    ]
    result["shipments"] = [
        shipment_data(shipment)
        for shipment in order.shipments.prefetch_related("lines__item").order_by("-id")
    ]
    return Response(result)



@api_view(["POST"])
@mutation
def order_action(request, pk, action):
    if action == "ship":
        allowed = ["packing", "manager"]
    elif action in ["confirm", "issue", "amend", "delete"]:
        allowed = ["sales", "manager"]
    else:
        allowed = ["manager"]
    s.permit(request.user, *allowed)
    order = locked_order(pk)
    if action == "confirm":
        s.confirm(order, request.user)
    elif action == "amend":
        s.amend(order, request.user, request.data)
        s.release_surplus(order, request.user)
    elif action == "replenish":
        s.replenish(order, request.user)
    elif action == "hold":
        s.ensure_open(order)
        order.hold_reason = s.reason(request.data)
        order.save(update_fields=["hold_reason"])
        s.stop_sessions(order=order)
        s.event(order, request.user, "Wstrzymano zamówienie", reason=order.hold_reason)
    elif action == "resume":
        s.ensure_open(order)
        order.hold_reason = ""
        order.save(update_fields=["hold_reason"])
        s.event(order, request.user, "Wznowiono zamówienie")
    elif action == "cancel":
        s.ensure_open(order)
        why = s.reason(request.data)
        order.cancelled_at = timezone.now()
        order.save(update_fields=["cancelled_at"])
        s.stop_sessions(order=order)
        s.event(order, request.user, "Anulowano zamówienie", reason=why)
        s.release_unshipped(order, request.user, "Anulowanie: " + why)
        s.release_surplus(order, request.user)
    elif action == "issue":
        if s.status(order) != "completed" or order.hold_reason:
            raise ValidationError("Najpierw zakończ wszystkie pozycje i usuń blokadę.")
        order.issued_at = timezone.now()
        order.save(update_fields=["issued_at"])
        s.stop_sessions(order=order)
        s.event(order, request.user, "Wydano zamówienie")
    elif action == "unissue":
        if not order.issued_at:
            raise ValidationError("Zamówienie nie jest wydane.")
        why = s.reason(request.data)
        order.issued_at = None
        order.save(update_fields=["issued_at"])
        s.event(order, request.user, "Cofnięto wydanie", reason=why)
    elif action == "delete":
        if order.confirmed_at or order.items.filter(labels__isnull=False).exists():
            raise ValidationError("Można usunąć tylko szkic bez etykiet.")
        order.delete()
    elif action == "ship":
        s.ship_order(order, request.user)
    else:
        raise ValidationError("Nieznana czynność.")
    return {"ok": True, "id": pk}



@api_view(["POST"])
@mutation
def task_action(request, pk, action):
    initial = get_object_or_404(Task, pk=pk)
    order = locked_order(initial.order_id)
    task = Task.objects.select_related("item", "product").get(pk=pk)
    task.order = order
    s.permit(
        request.user, task.kind if task.kind == "production" else "packing", "manager"
    )
    if action == "start":
        s.start(task, request.user)
    elif action == "pause":
        s.stop_sessions(task=task, user=request.user)
        s.event(order, request.user, "Wstrzymano licznik pracy", task_id=pk)
    elif action == "hold":
        s.ensure_open(order)
        task.hold_reason = s.reason(request.data)
        task.save(update_fields=["hold_reason"])
        s.stop_sessions(task=task)
        s.event(
            order,
            request.user,
            "Zgłoszono problem",
            task_id=pk,
            reason=task.hold_reason,
        )
    elif action == "resume":
        s.permit(request.user, "manager")
        task.hold_reason = ""
        task.save(update_fields=["hold_reason"])
        s.event(order, request.user, "Usunięto blokadę zadania", task_id=pk)
    elif action == "report":
        report = (
            s.production_report(task, request.user, request.data)
            if task.kind == "production"
            else s.packing_report(task, request.user, request.data)
        )
        return {"id": report.pk}
    elif action == "target":
        raise ValidationError(
            "Cel produkcji to liczba opakowań w zamówieniu. Zmień ilość zamówienia."
        )
    else:
        raise ValidationError("Nieznana czynność.")
    return {"ok": True}



@api_view(["POST"])
@mutation
def correction(request, pk):
    s.permit(request.user, "manager")
    report = get_object_or_404(Report.objects.select_related("task"), pk=pk)
    order = locked_order(report.task.order_id)
    report = Report.objects.select_related("task__item").get(pk=pk)
    report.task.order = order
    s.reverse_report(report, request.user, request.data)
    return {"ok": True}



def validate_file(upload):
    if not upload or upload.size > 20 * 1024 * 1024:
        raise ValidationError("Wybierz PDF, PNG lub JPG do 20 MB.")
    content = upload.read()
    upload.seek(0)
    try:
        if content.startswith(b"%PDF-"):
            document = PdfReader(io.BytesIO(content), strict=True)
            if document.is_encrypted or not len(document.pages):
                raise ValueError()
            return "application/pdf", s.file_sha256(content)
        image = Image.open(io.BytesIO(content))
        image.verify()
        if image.format not in ["PNG", "JPEG"]:
            raise ValueError()
        return "image/png" if image.format == "PNG" else "image/jpeg", s.file_sha256(content)
    except Exception:
        raise ValidationError("Plik nie jest poprawnym PDF, PNG ani JPG.")



@api_view(["POST"])
@mutation
def upload_label(request, pk):
    s.permit(request.user, "sales", "manager")
    item = get_object_or_404(Item, pk=pk)
    order = locked_order(item.order_id)
    s.ensure_open(order)
    upload = request.FILES.get("file")
    mime, digest = validate_file(upload)
    version = (item.labels.aggregate(v=Max("version"))["v"] or 0) + 1
    label = Label.objects.create(
        item=item,
        version=version,
        file=upload,
        filename=Path(upload.name).name[:200],
        mime=mime,
        content_sha256=digest,
        uploaded_by=request.user,
    )
    for task in item.tasks.filter(kind="production"):
        s.stop_sessions(task=task)
    s.event(
        order,
        request.user,
        "Dodano wersję etykiety",
        item_id=pk,
        version=version,
        already_packed=item.packed,
    )
    return {"id": label.pk}



@api_view(["POST"])
@mutation
def approve_label(request, pk):
    s.permit(request.user, "sales", "manager")
    label = get_object_or_404(Label.objects.select_related("item"), pk=pk)
    order = locked_order(label.item.order_id)
    s.ensure_open(order)
    if s.latest_label(label.item).pk != pk:
        raise ValidationError("Zatwierdź najnowszą wersję etykiety.")
    label.approved_at = timezone.now()
    label.approved_by = request.user
    label.save()
    s.allocate_custom(label.item, request.user, order)
    s.event(
        order,
        request.user,
        "Zatwierdzono etykietę",
        item_id=label.item_id,
        version=label.version,
    )
    return {"ok": True}



@api_view(["GET"])
def download_label(request, pk):
    s.permit(request.user, "sales", "production", "packing", "manager")
    label = get_object_or_404(Label, pk=pk)
    response = FileResponse(
        label.file.open("rb"),
        as_attachment=True,
        filename=label.filename,
        content_type=label.mime,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response



