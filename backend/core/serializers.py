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


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"
