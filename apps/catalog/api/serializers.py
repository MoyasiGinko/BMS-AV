"""DRF serializers for product catalog resources."""

from __future__ import annotations

from rest_framework import serializers

from apps.catalog.models import (
    Category,
    PriceList,
    PriceListItem,
    Product,
    ProductVariant,
    Unit,
)


class CategorySerializer(serializers.ModelSerializer[Category]):
    """Serializer for Category."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    parent_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.all_tenants.all(), source="parent", required=False, allow_null=True
    )

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "parent_id",
            "description",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class UnitSerializer(serializers.ModelSerializer[Unit]):
    """Serializer for Unit of Measure."""

    id = serializers.UUIDField(source="public_id", read_only=True)

    class Meta:
        model = Unit
        fields = [
            "id",
            "name",
            "code",
            "precision",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProductVariantSerializer(serializers.ModelSerializer[ProductVariant]):
    """Serializer for Product Variant."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    effective_cost_price = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    effective_selling_price = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)

    class Meta:
        model = ProductVariant
        fields = [
            "id",
            "sku",
            "barcode",
            "name",
            "attributes",
            "cost_price_override",
            "selling_price_override",
            "effective_cost_price",
            "effective_selling_price",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "effective_cost_price",
            "effective_selling_price",
            "created_at",
            "updated_at",
        ]


class ProductSerializer(serializers.ModelSerializer[Product]):
    """Serializer for Product."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.all_tenants.all(),
        source="category",
        required=False,
        allow_null=True,
    )
    unit_id = serializers.PrimaryKeyRelatedField(
        queryset=Unit.all_tenants.all(),
        source="unit",
    )
    category_name = serializers.CharField(source="category.name", read_only=True)
    unit_code = serializers.CharField(source="unit.code", read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "sku",
            "barcode",
            "name",
            "category_id",
            "category_name",
            "unit_id",
            "unit_code",
            "type",
            "cost_price",
            "selling_price",
            "tax_code",
            "track_batch",
            "track_serial",
            "reorder_level",
            "reorder_quantity",
            "is_active",
            "description",
            "variants",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "category_name",
            "unit_code",
            "variants",
            "created_at",
            "updated_at",
        ]


class PriceListItemSerializer(serializers.ModelSerializer[PriceListItem]):
    """Serializer for Price List Item override rule."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = PriceListItem
        fields = [
            "id",
            "product",
            "product_sku",
            "product_name",
            "variant",
            "price",
            "min_quantity",
        ]
        read_only_fields = ["id", "product_sku", "product_name"]


class PriceListSerializer(serializers.ModelSerializer[PriceList]):
    """Serializer for Price List."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    items = PriceListItemSerializer(many=True, read_only=True)

    class Meta:
        model = PriceList
        fields = [
            "id",
            "name",
            "currency",
            "is_default",
            "is_active",
            "description",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "items", "created_at", "updated_at"]
