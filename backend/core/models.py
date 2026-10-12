import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


def mass(**kwargs):
    return models.DecimalField(max_digits=14, decimal_places=3, **kwargs)


class Product(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    instruction = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#cf8c38")
    active = models.BooleanField(default=True)


class Variant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    sku = models.CharField(max_length=60, unique=True)
    name = models.CharField(max_length=160)
    weight_g = mass()
    packaging = models.CharField(max_length=160, default="Doypack kraft")
    custom_label = models.BooleanField(default=False)
    instruction = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(weight_g__gt=0), name="variant_positive_weight"
            )
        ]


class Customer(models.Model):
    delivery_addresses = models.JSONField(default=list, blank=True)
    name = models.CharField(max_length=180)
    contact = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    tax_id = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    active = models.BooleanField(default=True)


class Order(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.PROTECT
    )
    customer_snapshot = models.JSONField(default=dict)
    delivery_address_id = models.CharField(max_length=64, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, default="normal")
    delivery = models.CharField(max_length=15, default="courier")
    address = models.TextField(blank=True)
    production_notes = models.TextField(blank=True)
    packing_notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    issued_at = models.DateTimeField(null=True)
    cancelled_at = models.DateTimeField(null=True)
    hold_reason = models.TextField(blank=True)
    version = models.PositiveIntegerField(default=1)

    @property
    def number(self):
        return f"ZAM-{timezone.localtime(self.created_at).year}-{self.pk:05d}"


class Item(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    product_name = models.CharField(max_length=160)
    weight_g = mass()
    packaging = models.CharField(max_length=160)
    custom_label = models.BooleanField(default=False)
    instruction = models.TextField(blank=True)
    quantity = models.PositiveIntegerField()
    produced = models.PositiveIntegerField(default=0)
    allocated = models.PositiveIntegerField(default=0)
    packed = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="item_positive_qty"
            ),
            models.CheckConstraint(
                condition=Q(produced__lte=models.F("quantity")),
                name="item_produced_lte_qty",
            ),
            models.CheckConstraint(
                condition=Q(allocated__lte=models.F("quantity")),
                name="item_allocated_lte_qty",
            ),
            models.CheckConstraint(
                condition=Q(produced__lte=models.F("quantity") - models.F("allocated")),
                name="item_covered_lte_qty",
            ),
            models.CheckConstraint(
                condition=Q(packed__lte=models.F("allocated") + models.F("produced")),
                name="item_shipped_lte_ready",
            ),
            models.CheckConstraint(
                condition=Q(packed__lte=models.F("quantity")),
                name="item_packed_lte_qty",
            ),
        ]


class Task(models.Model):
    order = models.ForeignKey(Order, related_name="tasks", on_delete=models.CASCADE)
    kind = models.CharField(max_length=12)  # production / shipping
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_name = models.CharField(max_length=160)
    instruction = models.TextField(blank=True)
    item = models.ForeignKey(
        Item, null=True, blank=True, related_name="tasks", on_delete=models.CASCADE
    )
    target_g = mass(default=0)
    produced_g = mass(default=0)
    started_at = models.DateTimeField(null=True)
    hold_reason = models.TextField(blank=True)
    supplemental = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "item"],
                condition=Q(item__isnull=False),
                name="one_task_per_item_kind",
            )
        ]


class Batch(models.Model):
    origin = models.ForeignKey(Task, related_name="batches", on_delete=models.PROTECT)
    order = models.ForeignKey(
        Order, null=True, blank=True, related_name="batches", on_delete=models.PROTECT
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    available_g = mass(default=0)

    @property
    def number(self):
        return f"PART-{timezone.localtime(self.created_at):%Y%m%d}-{self.pk:05d}"

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(available_g__gte=0), name="batch_nonnegative"
            )
        ]


def label_path(instance, filename):
    return f"labels/{instance.item.order_id}/{uuid.uuid4().hex}"


class Label(models.Model):
    item = models.ForeignKey(Item, related_name="labels", on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    file = models.FileField(upload_to=label_path)
    filename = models.CharField(max_length=200)
    mime = models.CharField(max_length=50)
    uploaded_at = models.DateTimeField(default=timezone.now)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "version"], name="unique_label_version"
            )
        ]


class Report(models.Model):
    task = models.ForeignKey(Task, related_name="reports", on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    grams = mass(default=0)  # good production OR total packing consumption
    waste_g = mass(default=0)
    units = models.PositiveIntegerField(default=0)
    measured = models.BooleanField(default=False)
    batch = models.ForeignKey(Batch, null=True, on_delete=models.PROTECT)
    label = models.ForeignKey(Label, null=True, on_delete=models.PROTECT)
    note = models.TextField(blank=True)


class Movement(models.Model):
    batch = models.ForeignKey(Batch, related_name="movements", on_delete=models.PROTECT)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.PROTECT)
    report = models.ForeignKey(
        Report, null=True, related_name="movements", on_delete=models.PROTECT
    )
    delta_g = mass()
    reason = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)


class Shipment(models.Model):
    order = models.ForeignKey(Order, related_name="shipments", on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    address = models.TextField(blank=True)
    note = models.TextField(blank=True)

    @property
    def number(self):
        return f"PRZ-{timezone.localtime(self.created_at).year}-{self.pk:05d}"


class ShipmentLine(models.Model):
    shipment = models.ForeignKey(
        Shipment, related_name="lines", on_delete=models.CASCADE
    )
    item = models.ForeignKey(Item, related_name="shipment_lines", on_delete=models.PROTECT)
    units = models.PositiveIntegerField()
    report = models.OneToOneField(
        Report, null=True, related_name="shipment_line", on_delete=models.PROTECT
    )


class Correction(models.Model):
    report = models.OneToOneField(
        Report, related_name="correction", on_delete=models.PROTECT
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    reason = models.TextField()
    restored_mass = models.BooleanField(default=False)


class WorkSession(models.Model):
    task = models.ForeignKey(Task, related_name="sessions", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "user"],
                condition=Q(ended_at__isnull=True),
                name="one_running_session",
            )
        ]


class Event(models.Model):
    order = models.ForeignKey(
        Order, null=True, related_name="events", on_delete=models.CASCADE
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    action = models.CharField(max_length=100)
    detail = models.JSONField(default=dict)


class StockCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    position = models.PositiveIntegerField(default=0)
    system = models.BooleanField(default=False)


class Supplier(models.Model):
    name = models.CharField(max_length=180, unique=True)
    contact = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    active = models.BooleanField(default=True)


class StockItem(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=180)
    group = models.CharField(max_length=20)
    unit = models.CharField(max_length=10)
    quantity = mass(default=0)
    reserved = mass(default=0)
    position = models.PositiveIntegerField(default=0)
    category = models.ForeignKey(
        StockCategory, null=True, blank=True, related_name="items", on_delete=models.PROTECT
    )
    variant = models.ForeignKey(
        "Variant", null=True, blank=True, on_delete=models.PROTECT
    )
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, related_name="materials", on_delete=models.PROTECT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["variant"],
                condition=Q(variant__isnull=False),
                name="one_stock_per_variant",
            )
        ]


class Recipe(models.Model):
    variant = models.OneToOneField(
        Variant, related_name="recipe", on_delete=models.CASCADE
    )


class RecipeLine(models.Model):
    recipe = models.ForeignKey(Recipe, related_name="lines", on_delete=models.CASCADE)
    stock = models.ForeignKey(StockItem, related_name="recipe_lines", on_delete=models.PROTECT)
    quantity = mass()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "stock"], name="one_ingredient_per_recipe"
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="recipe_line_positive"
            ),
        ]


class StockMove(models.Model):
    item = models.ForeignKey(StockItem, related_name="moves", on_delete=models.PROTECT)
    delta = mass()
    reserved_delta = mass(default=0)
    quantity_after = mass()
    reason = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    report = models.ForeignKey(
        "Report", null=True, blank=True, on_delete=models.PROTECT
    )
    created_at = models.DateTimeField(default=timezone.now)


class RequestReceipt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "key"], name="unique_request_per_user"
            )
        ]
