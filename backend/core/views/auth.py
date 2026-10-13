import hashlib
import ipaddress
import json
import os
import uuid
from datetime import timedelta
from functools import wraps
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
)
from django.db import transaction, connection, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.throttling import BaseThrottle
from ..models import (
    Order,
    LoginBucket,
    RequestReceipt,
)
from .. import services as s
from ..presentation import (
    user_data,
)


class LoginThrottle(BaseThrottle):
    """Kept so the login route still declares a throttle. Limits are enforced in sign_in."""

    def allow_request(self, request, view):
        return True


def client_ip(request):
    """Use the proxy's client address only when the TCP peer is the private proxy.

    A public client cannot make Gunicorn see a private REMOTE_ADDR, so a forged
    X-Real-IP or X-Forwarded-For from the internet is ignored. Python treats
    documentation ranges as private, so only a globally routable peer ignores
    those headers. Nginx overwrites X-Real-IP and does not append the visitor's
    forwarded header.
    """
    peer = request.META.get("REMOTE_ADDR", "") or ""
    try:
        parsed = ipaddress.ip_address(peer)
        proxy = parsed.is_private or parsed.is_loopback
    except ValueError:
        proxy = False
    if not proxy:
        return peer
    forwarded = (request.META.get("HTTP_X_REAL_IP") or "").split(",")[0].strip()
    try:
        ipaddress.ip_address(forwarded)
    except ValueError:
        return peer
    return forwarded or peer


def login_wait(ident, limit):
    now = timezone.now()
    with transaction.atomic():
        bucket = LoginBucket.objects.select_for_update().filter(ident=ident).first()
        if bucket is None:
            try:
                with transaction.atomic():
                    LoginBucket.objects.create(
                        ident=ident, window_start=now, attempts=1
                    )
                return None
            except IntegrityError:
                bucket = LoginBucket.objects.select_for_update().get(ident=ident)
        if now - bucket.window_start >= timedelta(minutes=1):
            bucket.window_start = now
            bucket.attempts = 1
            bucket.save(update_fields=["window_start", "attempts"])
            return None
        if bucket.attempts >= limit:
            remaining = 60 - int((now - bucket.window_start).total_seconds())
            return max(1, remaining)
        bucket.attempts += 1
        bucket.save(update_fields=["attempts"])
        return None


def enforce_login_limits(request, username):
    ip_limit = int(os.environ.get("LOGIN_IP_LIMIT", "30"))
    account_limit = int(os.environ.get("LOGIN_ACCOUNT_LIMIT", "10"))
    ip_wait = login_wait("ip:" + client_ip(request), ip_limit)
    account = hashlib.sha256(username.strip().casefold().encode()).hexdigest()
    account_wait = login_wait("acct:" + account, account_limit)
    wait = max([value for value in (ip_wait, account_wait) if value] or [0])
    if wait:
        raise Throttled(
            wait=wait,
            detail=f"Zbyt wiele prób logowania. Spróbuj ponownie za {wait} s.",
        )



@api_view(["GET"])
@permission_classes([AllowAny])
def version(request):
    from core.version import app_version

    return Response({"version": app_version()})



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
    enforce_login_limits(request, str(request.data.get("username") or ""))
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
                    s.assert_receipt_workspace(
                        request.user, request.path, receipt.response
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



