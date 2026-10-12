"""DRF serializers for inventory API resources."""

from __future__ import annotations

from rest_framework import serializers

from apps.inventory.models import (
    StockAdjustment,
    StockAdjustmentLine,
    StockLevel,
    StockMovement,
    StockReservation,
    StockTransfer,
    StockTransferLine,
)


class StockLevelSerializer(serializers.ModelSerializer[StockLevel]):
    """Serializer for cached warehouse stock levels."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    product_id = serializers.UUIDField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    variant_id = serializers.UUIDField(source="variant.public_id", read_only=True, allow_null=True)
    variant_name = serializers.CharField(source="variant.name", read_only=True, allow_null=True)
    warehouse_id = serializers.UUIDField(source="warehouse.public_id", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    available = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    total_value = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockLevel
        fields = [
            "id",
            "product_id",
            "product_name",
            "product_sku",
            "variant_id",
            "variant_name",
            "warehouse_id",
            "warehouse_name",
            "on_hand",
            "reserved",
            "available",
            "avg_cost",
            "total_value",
            "reorder_point",
            "reorder_quantity",
            "is_low_stock",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "product_id",
            "product_name",
            "product_sku",
            "variant_id",
            "variant_name",
            "warehouse_id",
            "warehouse_name",
            "available",
            "total_value",
            "is_low_stock",
            "updated_at",
        ]


class StockMovementSerializer(serializers.ModelSerializer[StockMovement]):
    """Serializer for immutable stock movement ledger records."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    product_id = serializers.UUIDField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    variant_id = serializers.UUIDField(source="variant.public_id", read_only=True, allow_null=True)
    warehouse_id = serializers.UUIDField(source="warehouse.public_id", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product_id",
            "product_name",
            "product_sku",
            "variant_id",
            "warehouse_id",
            "warehouse_name",
            "type",
            "quantity",
            "unit_cost",
            "total_cost",
            "reference_type",
            "reference_id",
            "occurred_at",
            "notes",
            "created_at",
        ]
        read_only_fields = fields


class StockTransferLineSerializer(serializers.ModelSerializer[StockTransferLine]):
    """Serializer for stock transfer line items."""

    product_id = serializers.UUIDField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = StockTransferLine
        fields = ["id", "product_id", "product_name", "quantity"]


class StockTransferSerializer(serializers.ModelSerializer[StockTransfer]):
    """Serializer for stock transfer documents."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    source_warehouse_id = serializers.UUIDField(source="source_warehouse.public_id", read_only=True)
    destination_warehouse_id = serializers.UUIDField(source="destination_warehouse.public_id", read_only=True)
    source_branch_id = serializers.UUIDField(source="source_branch.public_id", read_only=True, default=None)
    source_branch_name = serializers.CharField(source="source_branch.name", read_only=True, default="")
    destination_branch_id = serializers.UUIDField(
        source="destination_branch.public_id", read_only=True, default=None
    )
    destination_branch_name = serializers.CharField(
        source="destination_branch.name", read_only=True, default=""
    )
    is_inter_branch = serializers.BooleanField(read_only=True)
    dispatched_at = serializers.DateTimeField(read_only=True)
    received_at = serializers.DateTimeField(read_only=True)
    lines = StockTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "transfer_number",
            "source_warehouse_id",
            "destination_warehouse_id",
            "source_branch_id",
            "source_branch_name",
            "destination_branch_id",
            "destination_branch_name",
            "is_inter_branch",
            "status",
            "notes",
            "dispatched_at",
            "received_at",
            "completed_at",
            "lines",
            "created_at",
        ]
        read_only_fields = fields


class StockAdjustmentLineSerializer(serializers.ModelSerializer[StockAdjustmentLine]):
    """Serializer for stock adjustment line items."""

    product_id = serializers.UUIDField(source="product.public_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = StockAdjustmentLine
        fields = ["id", "product_id", "product_name", "quantity", "unit_cost"]


class StockAdjustmentSerializer(serializers.ModelSerializer[StockAdjustment]):
    """Serializer for stock adjustment documents."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    warehouse_id = serializers.UUIDField(source="warehouse.public_id", read_only=True)
    lines = StockAdjustmentLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockAdjustment
        fields = [
            "id",
            "adjustment_number",
            "warehouse_id",
            "reason",
            "status",
            "notes",
            "confirmed_at",
            "lines",
            "created_at",
        ]
        read_only_fields = fields


class StockReservationSerializer(serializers.ModelSerializer[StockReservation]):
    """Serializer for stock reservations."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    product_id = serializers.UUIDField(source="product.public_id", read_only=True)
    warehouse_id = serializers.UUIDField(source="warehouse.public_id", read_only=True)

    class Meta:
        model = StockReservation
        fields = [
            "id",
            "product_id",
            "warehouse_id",
            "quantity",
            "reference_type",
            "reference_id",
            "status",
            "expires_at",
            "notes",
            "created_at",
        ]
        read_only_fields = fields
