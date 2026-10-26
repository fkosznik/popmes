from rest_framework import serializers
from .models import Product, Variant, Customer


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"

    def validate_color(self, value):
        import re

        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise serializers.ValidationError("Podaj kolor w formacie #RRGGBB.")
        return value


class VariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Variant
        fields = "__all__"

    def validate_weight_g(self, value):
        if value <= 0:
            raise serializers.ValidationError("Masa musi być dodatnia.")
        return value


def format_delivery_address(data):
    street = data["street"].strip()
    house = data["house_number"].strip()
    apartment = (data.get("apartment") or "").strip()
    building = f"{house}/{apartment}" if apartment else house
    return f"{street} {building}, {data['postal_code'].strip()} {data['city'].strip()}"


class DeliveryAddressSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=180, allow_blank=True, required=False)
    address = serializers.CharField(max_length=2000, allow_blank=True, required=False)
    postal_code = serializers.CharField(max_length=12, allow_blank=True, required=False)
    city = serializers.CharField(max_length=80, allow_blank=True, required=False)
    street = serializers.CharField(max_length=120, allow_blank=True, required=False)
    house_number = serializers.CharField(max_length=20, allow_blank=True, required=False)
    apartment = serializers.CharField(max_length=20, allow_blank=True, required=False)

    def validate(self, data):
        structured = any(
            (data.get(key) or "").strip()
            for key in ("postal_code", "city", "street", "house_number", "apartment")
        )
        legacy = (data.get("address") or "").strip()
        if structured or not legacy:
            missing = [
                label
                for key, label in (
                    ("postal_code", "kod pocztowy"),
                    ("city", "miasto"),
                    ("street", "ulicę"),
                    ("house_number", "numer domu"),
                )
                if not (data.get(key) or "").strip()
            ]
            if missing:
                raise serializers.ValidationError(
                    "Uzupełnij adres dostawy: " + ", ".join(missing) + "."
                )
            data["address"] = format_delivery_address(data)
        if not (data.get("name") or "").strip():
            data["name"] = ((data.get("city") or "").strip() or "Dostawa")[:180]
        return data


class CustomerSerializer(serializers.ModelSerializer):
    delivery_addresses = DeliveryAddressSerializer(many=True, required=False)

    def validate(self, attrs):
        if self.instance is None and not attrs.get("delivery_addresses"):
            raise serializers.ValidationError(
                {"delivery_addresses": "Dodaj adres dostawy."}
            )
        return attrs

    def validate_delivery_addresses(self, value):
        if len(value) > 50 or len({a["id"] for a in value}) != len(value):
            raise serializers.ValidationError(
                "Maksymalnie 50 adresów o unikalnych identyfikatorach."
            )
        return value

    class Meta:
        model = Customer
        fields = "__all__"
