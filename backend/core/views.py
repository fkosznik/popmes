import hashlib
import io
import json
import uuid
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
from rest_framework.throttling import AnonRateThrottle
from PIL import Image
from pypdf import PdfReader
from .models import (
    Product,
    Variant,
    Customer,
    Order,
    Item,
    Task,
    Batch,
    Report,
    Label,
    RequestReceipt,
    Profile,
    StockItem,
    Supplier,
    Workspace,
)
from django.db.models import Max
from .serializers import ProductSerializer, VariantSerializer, CustomerSerializer
from . import services as s
from .presentation import (
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


class LoginThrottle(AnonRateThrottle):
    scope = "login"


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return Response({"status": "ok"})


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    return Response(
        {"user": user_data(request.user) if request.user.is_authenticated else None}
    )


@csrf_protect
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def sign_in(request):
    SessionAuthentication().enforce_csrf(request)
    user = authenticate(
        request,
        username=request.data.get("username"),
        password=request.data.get("password"),
    )
    if not user:
        raise ValidationError("Nieprawidłowy login lub hasło.")
    login(request, user)
    return Response({"user": user_data(user)})


@api_view(["POST"])
def sign_out(request):
    s.stop_sessions(user=request.user)
    logout(request)
    return Response({"ok": True})


def mutation(fn):
    """Serialize a user's retries. Domain functions also lock all affected orders."""

    @wraps(fn)
    def wrapped(request, *args, **kwargs):
        try:
            key = uuid.UUID(request.headers.get("Idempotency-Key", ""))
        except ValueError:
            raise ValidationError("Brak poprawnego Idempotency-Key.")
        payload = {}
        for k, value in request.data.items():
            if hasattr(value, "chunks"):
                if value.size > 20 * 1024 * 1024:
                    raise ValidationError("Maksymalny rozmiar pliku to 20 MB.")
                digest = hashlib.sha256()
                for chunk in value.chunks():
                    digest.update(chunk)
                value.seek(0)
                payload[k] = digest.hexdigest()
            else:
                payload[k] = value
        fingerprint = hashlib.sha256(
            json.dumps([request.path, payload], sort_keys=True, default=str).encode()
        ).hexdigest()
        try:
            with transaction.atomic():
                # Serialize retries without blocking foreign-key checks from
                # other workers' audit records at transaction commit.
                get_user_model().objects.select_for_update(no_key=True).get(
                    pk=request.user.pk
                )
                receipt = RequestReceipt.objects.filter(
                    user=request.user, key=key
                ).first()
                if receipt:
                    if receipt.fingerprint != fingerprint:
                        raise ValidationError(
                            "Ten identyfikator zapisu został już użyty dla innych danych."
                        )
                    return Response(receipt.response)
                result = fn(request, *args, **kwargs)
                RequestReceipt.objects.create(
                    user=request.user, key=key, fingerprint=fingerprint, response=result
                )
                return Response(result)
        except IntegrityError:
            raise ValidationError(
                "Konflikt danych. Sprawdź unikalność kodów i odśwież dane."
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError("Niepoprawne dane żądania.") from exc

    return wrapped


def locked_order(pk):
    return get_object_or_404(Order.objects.select_for_update(), pk=pk)


def shell_settings(user):
    space = s.current_workspace(user)
    return {
        "organization": organization_data(s.organization()),
        "workspaces": workspaces_data(),
        "workspace_id": space.pk,
    }


@api_view(["GET"])
def state(request):
    r = s.roles(request.user)
    settings_payload = shell_settings(request.user)
    if not r:
        return Response(
            {
                "user": user_data(request.user),
                "orders": [],
                "tasks": [],
                "products": [],
                "variants": [],
                "customers": [],
                "batches": [],
                "stock": [],
                "categories": [],
                "suppliers": [],
                **settings_payload,
            }
        )
    commercial = bool(set(r) & {"sales", "manager"})
    kinds = (
        ["production", "shipping"]
        if "manager" in r
        else [
            k
            for role, k in [("production", "production"), ("packing", "shipping")]
            if role in r
        ]
    )
    order_q, _space = s.workspace_filter(request.user)
    orders = Order.objects.select_related("customer").filter(order_q).order_by("-id")
    tasks = (
        Task.objects.select_related("order", "order__customer", "product", "item")
        .filter(
            s.workspace_q(_space, "order__"),
            kind__in=kinds,
            order__cancelled_at__isnull=True,
            order__issued_at__isnull=True,
        )
        .order_by("-order__priority", "order__due_at", "id")
    )
    see_stock = bool(set(r) & {"sales", "manager", "production", "packing", "admin"})
    stock_by_variant = {}
    categories = []
    stock = []
    if see_stock:
        stock = [stock_data(item) for item in s.stock_rows()]
        categories = [category_data(item) for item in s.category_rows()]
        stock_by_variant = {
            item["variant_id"]: item for item in stock if item["variant_id"]
        }
    variants = VariantSerializer(
        Variant.objects.all().order_by("name"), many=True
    ).data
    recipes = s.recipe_rows()
    for row in variants:
        level = stock_by_variant.get(row["id"])
        row["stock_quantity"] = level["quantity"] if level else "0"
        row["stock_available"] = level["available"] if level else "0"
        row["recipe"] = recipes.get(row["id"], [])
    return Response(
        {
            "user": user_data(request.user),
            "orders": [order_data(o) for o in orders] if commercial else [],
            "tasks": [task_data(t, request.user) for t in tasks],
            "products": ProductSerializer(
                Product.objects.all().order_by("name"), many=True
            ).data,
            "variants": variants,
            "customers": CustomerSerializer(
                Customer.objects.all().order_by("name"), many=True
            ).data
            if commercial
            else [],
            "batches": [
                batch_data(b)
                for b in Batch.objects.filter(available_g__gt=0).select_related(
                    "origin"
                )
            ]
            if commercial or "production" in r or "packing" in r
            else [],
            "stock": stock,
            "categories": categories,
            "suppliers": [supplier_data(item) for item in s.supplier_rows()],
            **settings_payload,
        }
    )


@api_view(["POST"])
@mutation
def catalog(request, kind):
    options = {
        "products": (Product, ProductSerializer, ["admin", "manager"]),
        "variants": (Variant, VariantSerializer, ["admin", "manager"]),
        "customers": (Customer, CustomerSerializer, ["sales", "manager"]),
    }
    if kind not in options:
        raise ValidationError("Nieznany katalog.")
    model, serializer, allowed = options[kind]
    s.permit(request.user, *allowed)
    instance = (
        get_object_or_404(model, pk=request.data["id"])
        if request.data.get("id")
        else None
    )
    payload = dict(request.data)
    if kind == "customers" and not instance:
        payload["active"] = True
    form = serializer(instance, data=payload, partial=bool(instance))
    form.is_valid(raise_exception=True)
    value = form.save()
    if kind == "variants":
        s.sync_catalog_stock()
    s.event(None, request.user, "Zapisano katalog", kind=kind, id=value.pk)
    return {"id": value.pk}


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
            uploads[index] = (upload, validate_file(upload))
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
            upload, mime = uploads[index]
            Label.objects.create(
                item=item,
                version=1,
                file=upload,
                filename=Path(upload.name).name[:200],
                mime=mime,
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
            return "application/pdf"
        image = Image.open(io.BytesIO(content))
        image.verify()
        if image.format not in ["PNG", "JPEG"]:
            raise ValueError()
        return "image/png" if image.format == "PNG" else "image/jpeg"
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
    mime = validate_file(upload)
    version = (item.labels.aggregate(v=Max("version"))["v"] or 0) + 1
    label = Label.objects.create(
        item=item,
        version=version,
        file=upload,
        filename=Path(upload.name).name[:200],
        mime=mime,
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


@api_view(["POST"])
@mutation
def stock_action(request, pk):
    s.permit(request.user, "manager")
    initial = get_object_or_404(Batch, pk=pk)
    target_id = request.data.get("order_id")
    ids = sorted(
        {
            i
            for i in [initial.order_id, int(target_id) if target_id else None]
            if i is not None
        }
    )
    orders = {
        o.pk: o
        for o in Order.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    }
    s.lock_products([initial.product_id])
    batch = Batch.objects.select_for_update().get(pk=pk)
    if batch.order_id != initial.order_id:
        raise ValidationError("Partia została przeniesiona. Odśwież dane.")
    source = orders.get(batch.order_id)
    why = s.reason(request.data)
    if target_id:
        target = orders.get(int(target_id))
        if not target or (source and target.pk == source.pk) or not target.confirmed_at:
            raise ValidationError("Wybierz inne zatwierdzone zamówienie.")
        s.ensure_open(target)
        if not target.items.filter(product=batch.product).exists():
            raise ValidationError("Smak partii nie pasuje do zamówienia.")
        # Transfer the full remaining balance, retaining original batch identity.
        grams = batch.available_g
        if grams <= 0:
            raise ValidationError("Partia jest pusta.")
        s.movement(batch, source, request.user, -grams, "Transfer do " + target.number)
        batch.order = target
        batch.save(update_fields=["order"])
        s.movement(
            batch,
            target,
            request.user,
            grams,
            "Transfer z " + (source.number if source else "magazynu"),
        )
        s.event(
            target,
            request.user,
            "Przyjęto partię",
            batch=batch.number,
            grams=str(grams),
            reason=why,
        )
        s.event(
            source,
            request.user,
            "Przeniesiono partię",
            batch=batch.number,
            target=target.number,
            grams=str(grams),
            reason=why,
        )
    else:
        grams = s.decimal(request.data.get("grams"), positive=True)
        s.movement(batch, source, request.user, -grams, why)
        s.event(
            source,
            request.user,
            "Rozchód popcornu",
            batch=batch.number,
            grams=str(grams),
            reason=why,
        )
    return {"ok": True}


ACCOUNT_LANGUAGES = {"pl", "en"}
ACCOUNT_ZONES = {
    "Europe/Warsaw",
    "Europe/Berlin",
    "Europe/Prague",
    "Europe/London",
    "UTC",
}
ACCOUNT_PAGES = {
    "dashboard",
    "orders",
    "production",
    "shipping",
    "stock",
    "catalog",
    "customers",
    "users",
    "admin",
}


@api_view(["POST"])
@mutation
def account_update(request):
    data = request.data
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValidationError("Podaj imię lub nazwę.")
    email = str(data.get("email", "")).strip()
    if email:
        try:
            validate_email(email)
        except DjangoValidationError:
            raise ValidationError("Podaj poprawny e-mail.")
    language = str(data.get("language", "pl"))
    zone = str(data.get("timezone", "Europe/Warsaw"))
    start_page = str(data.get("start_page", "dashboard"))
    appearance = str(data.get("appearance", "light"))
    if (
        language not in ACCOUNT_LANGUAGES
        or zone not in ACCOUNT_ZONES
        or start_page not in ACCOUNT_PAGES
        or appearance not in {"light", "dark"}
    ):
        raise ValidationError(
            "Wybierz język, strefę czasową, ekran startowy i wygląd z listy."
        )
    user = request.user
    user.first_name = name[:150]
    user.email = email
    user.save(update_fields=["first_name", "email"])
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.phone = str(data.get("phone", ""))[:40]
    profile.street = str(data.get("street", ""))[:180]
    profile.postal_code = str(data.get("postal_code", ""))[:20]
    profile.city = str(data.get("city", ""))[:80]
    profile.country = str(data.get("country", ""))[:80]
    profile.language = language
    profile.timezone = zone
    profile.start_page = start_page
    profile.appearance = appearance
    profile.save()
    return user_data(user)


@api_view(["POST"])
@mutation
def account_password(request):
    user = request.user
    if not user.check_password(str(request.data.get("current_password", ""))):
        raise ValidationError("Obecne hasło jest nieprawidłowe.")
    password = str(request.data.get("password", ""))
    if password != str(request.data.get("password_repeat", "")):
        raise ValidationError("Nowe hasła nie są takie same.")
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages)
    user.set_password(password)
    user.save(update_fields=["password"])
    update_session_auth_hash(getattr(request, "_request", request), user)
    return {"ok": True}


@api_view(["GET", "POST"])
def users(request):
    s.permit(request.user, "admin")
    if request.method == "GET":
        return Response(
            [user_data(u) for u in get_user_model().objects.order_by("username")]
        )
    return save_user(request)


@mutation
def save_user(request):
    data = request.data
    user = (
        get_object_or_404(get_user_model(), pk=data["id"])
        if data.get("id")
        else get_user_model()()
    )
    is_new = user.pk is None
    if user.is_superuser and not request.user.is_superuser:
        raise ValidationError("Tylko superadministrator może zmieniać to konto.")
    if user.pk == request.user.pk and (
        data.get("active") is False or "admin" not in data.get("roles", [])
    ):
        raise ValidationError("Nie możesz odebrać sobie dostępu do administracji.")
    user.username = str(data.get("username", user.username)).strip()[:150]
    if not user.username:
        raise ValidationError("Podaj login.")
    user.first_name = str(data.get("name", user.first_name))[:150]
    user.is_active = data.get("active", True)
    selected = data.get("roles", [])
    if not selected or set(selected) - set(s.ROLES):
        raise ValidationError("Wybierz poprawne role.")
    password = data.get("password")
    if password:
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        user.set_password(password)
    elif not user.pk:
        raise ValidationError("Podaj hasło nowego użytkownika.")
    user.save()
    if is_new:
        profile, _created = Profile.objects.get_or_create(user=user)
        profile.language = s.organization().default_language
        profile.save(update_fields=["language"])
    user.groups.set([Group.objects.get_or_create(name=r)[0] for r in selected])
    s.event(
        None,
        request.user,
        "Zmieniono użytkownika",
        id=user.pk,
        roles=selected,
        active=user.is_active,
    )
    return {"id": user.pk}


@api_view(["POST"])
@mutation
def organization_update(request):
    s.permit(request.user, "admin")
    name = str(request.data.get("name", "")).strip()
    if not name:
        raise ValidationError("Podaj nazwę organizacji.")
    language = str(request.data.get("default_language", "pl"))
    theme = str(request.data.get("theme", "plum"))
    if language not in ACCOUNT_LANGUAGES or theme not in s.THEMES:
        raise ValidationError("Wybierz język i motyw z listy.")
    org = s.organization()
    org.name = name[:80]
    org.default_language = language
    org.theme = theme
    org.save(update_fields=["name", "default_language", "theme"])
    s.event(None, request.user, "Zmieniono ustawienia organizacji", name=org.name)
    return organization_data(org)


@api_view(["POST"])
@mutation
def workspace_save(request):
    s.permit(request.user, "admin")
    data = request.data
    space = (
        get_object_or_404(Workspace, pk=data["id"])
        if data.get("id")
        else Workspace(primary=False, active=True)
    )
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValidationError("Podaj nazwę przestrzeni produkcyjnej.")
    if Workspace.objects.exclude(pk=space.pk).filter(name__iexact=name).exists():
        raise ValidationError("Taka przestrzeń już istnieje.")
    space.name = name[:80]
    if space.pk and "active" in data:
        active = bool(data.get("active"))
        if space.primary and not active:
            raise ValidationError("Domyślnej przestrzeni nie można wyłączyć.")
        if (
            not active
            and not Workspace.objects.exclude(pk=space.pk).filter(active=True).exists()
        ):
            raise ValidationError("Zostaw przynajmniej jedną aktywną przestrzeń.")
        if space.active and not active:
            Profile.objects.filter(current_workspace=space).update(current_workspace=None)
        space.active = active
    space.save()
    s.event(
        None,
        request.user,
        "Zapisano przestrzeń produkcyjną",
        id=space.pk,
        name=space.name,
        active=space.active,
    )
    return {
        "id": space.pk,
        "name": space.name,
        "active": space.active,
        "primary": space.primary,
    }


@api_view(["POST"])
@mutation
def workspace_select(request):
    space = get_object_or_404(Workspace, pk=request.data.get("id"), active=True)
    profile, _created = Profile.objects.get_or_create(user=request.user)
    profile.current_workspace = space
    profile.save(update_fields=["current_workspace"])
    return {"id": space.pk}


@api_view(["POST"])
@mutation
def set_stock(request, pk):
    s.permit(request.user, "manager")
    get_object_or_404(StockItem, pk=pk)
    s.set_stock_quantity(
        pk, request.data.get("quantity"), request.user, s.reason(request.data)
    )
    return {"ok": True}


@api_view(["POST"])
@mutation
def stock_category(request):
    s.permit(request.user, "manager")
    category = s.add_category(request.data.get("name"))
    return {"id": category.pk}


@api_view(["POST"])
@mutation
def stock_product(request):
    s.permit(request.user, "manager")
    item = s.add_stock_product(
        request.data.get("category_id"),
        request.data.get("name"),
        request.data.get("unit"),
        request.data.get("supplier_id"),
    )
    return {"id": item.pk}


@api_view(["POST"])
@mutation
def supplier_create(request):
    s.permit(request.user, "manager")
    supplier = s.add_supplier(request.data)
    return {"id": supplier.pk}


@api_view(["POST"])
@mutation
def stock_supplier(request, pk):
    s.permit(request.user, "manager")
    get_object_or_404(StockItem, pk=pk)
    s.assign_supplier(pk, request.data.get("supplier_id"))
    return {"ok": True}


@api_view(["GET"])
def stock_detail(request, pk):
    s.permit(request.user, "sales", "manager", "production", "packing", "admin")
    item = get_object_or_404(
        StockItem.objects.select_related(
            "category", "supplier", "variant", "variant__product"
        ),
        pk=pk,
    )
    return Response(stock_profile(item))


@api_view(["POST"])
@mutation
def stock_edit(request, pk):
    s.permit(request.user, "manager")
    get_object_or_404(StockItem, pk=pk)
    s.update_stock_item(pk, request.data)
    return {"ok": True}


@api_view(["POST"])
@mutation
def supplier_update(request, pk):
    s.permit(request.user, "manager")
    get_object_or_404(Supplier, pk=pk)
    s.update_supplier(pk, request.data)
    return {"ok": True}


@api_view(["POST"])
@mutation
def recipe_save(request):
    s.permit(request.user, "manager")
    s.save_recipe(request.data.get("variant_id"), request.data.get("lines") or [])
    return {"ok": True}


@api_view(["POST"])
@mutation
def stock_receipt(request):
    s.permit(request.user, "manager")
    get_object_or_404(StockItem, pk=request.data.get("stock_id"))
    s.receive_stock(
        request.data.get("stock_id"),
        request.data.get("quantity"),
        request.user,
        s.reason(request.data),
    )
    return {"ok": True}
