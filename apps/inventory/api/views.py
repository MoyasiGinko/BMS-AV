"""DRF API ViewSets for inventory resources."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.inventory import services
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


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List stock levels across warehouses"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve stock level for warehouse item"),
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


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List stock movement ledger entries"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve stock movement entry"),
)
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


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List warehouse stock transfers"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve stock transfer document"),
    create=extend_schema(tags=["Inventory"], summary="Create stock transfer document"),
    update=extend_schema(tags=["Inventory"], summary="Update stock transfer document"),
    partial_update=extend_schema(tags=["Inventory"], summary="Partially update stock transfer document"),
    destroy=extend_schema(tags=["Inventory"], summary="Delete draft stock transfer document"),
)
class StockTransferViewSet(TenantScopedModelViewSet):
    """API endpoint for stock transfer documents."""

    queryset = (
        StockTransfer.objects.select_related(
            "source_warehouse",
            "destination_warehouse",
            "source_branch",
            "destination_branch",
        )
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
        "dispatch": "inventory.transfer",
        "receive": "inventory.transfer",
    }
    search_fields = ["transfer_number", "notes"]
    ordering_fields = ["created_at", "transfer_number"]
    ordering = ["-created_at"]

    @extend_schema(tags=["Inventory"], summary="Dispatch draft stock transfer into transit")
    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Dispatch a draft stock transfer into transit."""
        transfer = self.get_object()
        org = self.get_tenant()
        transfer = services.dispatch_stock_transfer(
            organization=org,
            transfer=transfer,
            actor=request.user,
        )
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Inventory"], summary="Receive in-transit stock transfer at destination warehouse")
    @action(detail=True, methods=["post"], url_path="receive")
    def receive(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Receive an in-transit stock transfer at the destination warehouse."""
        transfer = self.get_object()
        org = self.get_tenant()
        transfer = services.receive_stock_transfer(
            organization=org,
            transfer=transfer,
            actor=request.user,
        )
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List stock adjustment records"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve stock adjustment record"),
    create=extend_schema(tags=["Inventory"], summary="Create stock adjustment record"),
    update=extend_schema(tags=["Inventory"], summary="Update stock adjustment record"),
    partial_update=extend_schema(tags=["Inventory"], summary="Partially update stock adjustment record"),
    destroy=extend_schema(tags=["Inventory"], summary="Delete draft stock adjustment record"),
)
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


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List inventory reservations"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve inventory reservation"),
)
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
