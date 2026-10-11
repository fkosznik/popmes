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
    due_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, default="normal")
    delivery = models.CharField(max_length=15, default="pickup")
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
    packed = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="item_positive_qty"
            ),
            models.CheckConstraint(
                condition=Q(packed__lte=models.F("quantity")),
                name="item_packed_lte_qty",
            ),
        ]


class Task(models.Model):
    order = models.ForeignKey(Order, related_name="tasks", on_delete=models.CASCADE)
    kind = models.CharField(max_length=12)  # production / packing
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    product_name = models.CharField(max_length=160)
    instruction = models.TextField(blank=True)
    item = models.OneToOneField(Item, null=True, blank=True, on_delete=models.CASCADE)
    target_g = mass(default=0)
    produced_g = mass(default=0)
    started_at = models.DateTimeField(null=True)
    hold_reason = models.TextField(blank=True)
    supplemental = models.BooleanField(default=False)


class Batch(models.Model):
    origin = models.ForeignKey(Task, related_name="batches", on_delete=models.PROTECT)
    order = models.ForeignKey(Order, related_name="batches", on_delete=models.PROTECT)
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
    order = models.ForeignKey(Order, on_delete=models.PROTECT)
    report = models.ForeignKey(
        Report, null=True, related_name="movements", on_delete=models.PROTECT
    )
    delta_g = mass()
    reason = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)


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
