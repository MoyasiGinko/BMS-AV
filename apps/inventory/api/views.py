"""DRF API ViewSets for inventory resources."""

from __future__ import annotations

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.inventory.api.serializers import (
    StockAdjustmentSerializer,
    StockLevelSerializer,
    StockMovementSerializer,
    StockReservationSerializer,
    StockTransferSerializer,
)
from apps.inventory.models import (
    StockAdjustment,
    StockLevel,
    StockMovement,
    StockReservation,
    StockTransfer,
)


class StockLevelViewSet(TenantScopedModelViewSet):
    """API endpoint for inspecting warehouse stock levels."""

    queryset = StockLevel.objects.select_related("product", "variant", "warehouse").all()
    serializer_class = StockLevelSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
    }
    search_fields = ["product__name", "product__sku", "warehouse__name"]
    ordering_fields = ["product__name", "on_hand", "avg_cost"]
    ordering = ["product__name"]


class StockMovementViewSet(TenantScopedModelViewSet):
    """API endpoint for reading the immutable stock movement ledger."""

    queryset = StockMovement.objects.select_related("product", "variant", "warehouse").all()
    serializer_class = StockMovementSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
    }
    search_fields = ["product__name", "product__sku", "warehouse__name", "reference_type", "reference_id"]
    ordering_fields = ["occurred_at", "quantity"]
    ordering = ["-occurred_at"]


class StockTransferViewSet(TenantScopedModelViewSet):
    """API endpoint for stock transfer documents."""

    queryset = (
        StockTransfer.objects.select_related("source_warehouse", "destination_warehouse")
        .prefetch_related("lines__product")
        .all()
    )
    serializer_class = StockTransferSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "create": "inventory.transfer",
    }
    search_fields = ["transfer_number", "notes"]
    ordering_fields = ["created_at", "transfer_number"]
    ordering = ["-created_at"]


class StockAdjustmentViewSet(TenantScopedModelViewSet):
    """API endpoint for stock adjustments."""

    queryset = StockAdjustment.objects.select_related("warehouse").prefetch_related("lines__product").all()
    serializer_class = StockAdjustmentSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "create": "inventory.adjust",
    }
    search_fields = ["adjustment_number", "notes", "reason"]
    ordering_fields = ["created_at", "adjustment_number"]
    ordering = ["-created_at"]


class StockReservationViewSet(TenantScopedModelViewSet):
    """API endpoint for stock reservations."""

    queryset = StockReservation.objects.select_related("product", "variant", "warehouse").all()
    serializer_class = StockReservationSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
    }
    search_fields = ["product__name", "reference_type", "reference_id"]
    ordering_fields = ["created_at", "quantity"]
    ordering = ["-created_at"]
