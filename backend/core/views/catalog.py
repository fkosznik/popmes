from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from ..models import (
    Product,
    Variant,
    Customer,
    Task,
    Batch,
)
from ..serializers import ProductSerializer, VariantSerializer, CustomerSerializer
from .. import services as s
from ..presentation import (
    user_data,
    task_data,
    order_data,
    batch_data,
    stock_data,
    category_data,
    supplier_data,
    organization_data,
    workspaces_data,
)


from core.views.auth import mutation

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
                "summary": {
                    "orders": 0,
                    "active": 0,
                    "overdue": 0,
                    "production_remaining": 0,
                    "packing_remaining": 0,
                },
                "orders_page": {"limit": 0, "offset": 0, "count": 0},
                "tasks": [],
                "products": [],
                "variants": [],
                "customers": [],
                "batches": [],
                "stock": [],
                "categories": [],
                "suppliers": [],
                "undo": s.undo_for(request.user),
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
    _order_q, _space = s.workspace_filter(request.user)
    order_rows, summary, orders_page = s.select_orders(request.user, request.query_params)
    tasks = (
        Task.objects.select_related(
            "order", "order__customer", "product", "item", "item__variant"
        )
        .prefetch_related(
            "sessions__user",
            "item__labels",
            "order__items__labels",
            "order__batches__origin",
        )
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
            item["variant_id"]: item
            for item in stock
            if item["variant_id"] and not item["artwork_sha256"] and not item["artwork_unknown"]
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
            "orders": [order_data(o) for o in order_rows] if commercial else [],
            "summary": summary,
            "orders_page": orders_page,
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
            "undo": s.undo_for(request.user),
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
        s.sync_catalog_stock(value)
    s.event(None, request.user, "Zapisano katalog", kind=kind, id=value.pk)
    return {"id": value.pk}


@api_view(["POST"])
@mutation
def delete_product(request, pk):
    s.permit(request.user, "admin", "manager")
    get_object_or_404(Product, pk=pk)
    s.remove_product(pk, request.user)
    return {"ok": True}


@api_view(["POST"])
@mutation
def delete_variant(request, pk):
    s.permit(request.user, "admin", "manager")
    get_object_or_404(Variant, pk=pk)
    s.remove_variant(pk, request.user)
    return {"ok": True}


@api_view(["POST"])
@mutation
def delete_customer(request, pk):
    s.permit(request.user, "sales", "manager")
    get_object_or_404(Customer, pk=pk)
    s.remove_customer(pk, request.user)
    return {"ok": True}


@api_view(["POST"])
@mutation
def restore_product(request, pk):
    s.permit(request.user, "admin", "manager")
    get_object_or_404(Product, pk=pk)
    s.restore_product(pk)
    return {"ok": True}


@api_view(["POST"])
@mutation
def restore_variant(request, pk):
    s.permit(request.user, "admin", "manager")
    get_object_or_404(Variant, pk=pk)
    s.restore_variant(pk)
    return {"ok": True}


@api_view(["POST"])
@mutation
def restore_customer(request, pk):
    s.permit(request.user, "sales", "manager")
    get_object_or_404(Customer, pk=pk)
    s.restore_customer(pk)
    return {"ok": True}


@api_view(["POST"])
@mutation
def undo_last(request):
    s.apply_undo(request.user)
    return {"ok": True}



