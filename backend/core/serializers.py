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


class DeliveryAddressSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64)
    name = serializers.CharField(max_length=180)
    address = serializers.CharField(max_length=2000)


class CustomerSerializer(serializers.ModelSerializer):
    delivery_addresses = DeliveryAddressSerializer(many=True, required=False)

    def validate_delivery_addresses(self, value):
        if len(value) > 50 or len({a["id"] for a in value}) != len(value):
            raise serializers.ValidationError(
                "Maksymalnie 50 adresów o unikalnych identyfikatorach."
            )
        return value

    class Meta:
        model = Customer
        fields = "__all__"
