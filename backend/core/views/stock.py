from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from ..models import (
    StockItem,
    Supplier,
)
from .. import services as s
from ..presentation import (
    stock_profile,
)


from core.views.auth import mutation

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



