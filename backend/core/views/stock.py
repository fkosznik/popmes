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



