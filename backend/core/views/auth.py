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


class LoginThrottle(BaseThrottle):
    """Ten attempts per minute, counted in PostgreSQL so every Gunicorn worker shares it."""

    rate = 10

    def allow_request(self, request, view):
        address = request.META.get("REMOTE_ADDR", "")
        ident = hashlib.sha256(address.encode()).hexdigest()
        window = timezone.now() - timedelta(minutes=1)
        if LoginAttempt.objects.filter(ident=ident, created_at__gte=window).count() >= self.rate:
            return False
        LoginAttempt.objects.create(ident=ident)
        return True



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



