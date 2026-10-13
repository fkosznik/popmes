from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from ..models import (
    Order,
    Batch,
)
from .. import services as s


from core.views.auth import mutation

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



