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
    InventoryReconciliationIncidentSerializer,
    StockAdjustmentSerializer,
    StockLevelSerializer,
    StockMovementSerializer,
    StockReservationSerializer,
    StockTransferSerializer,
)
from apps.inventory.models import (
    InventoryReconciliationIncident,
    StockAdjustment,
    StockLevel,
    StockMovement,
    StockReservation,
    StockTransfer,
)

# Re-exported from apps.warehouses.api.views for backwards compatibility
from apps.warehouses.api.views import (
    InventoryLocationViewSet,
    StockSupplyRouteViewSet,
)


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List inventory reconciliation incidents"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve reconciliation incident"),
)
class InventoryReconciliationViewSet(TenantScopedModelViewSet):
    """API endpoint for inventory audit reconciliation and discrepancy incidents."""

    queryset = InventoryReconciliationIncident.objects.select_related("location", "product", "resolved_by").all()
    serializer_class = InventoryReconciliationIncidentSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
        "scan": "inventory.reconciliation_manage",
        "resolve": "inventory.reconciliation_manage",
    }
    ordering_fields = ["created_at", "incident_number"]
    ordering = ["-created_at"]

    @extend_schema(tags=["Inventory"], summary="Scan system for ledger-balance drift and anomalies")
    @action(detail=False, methods=["post"], url_path="scan")
    def scan(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Scan all locations for inventory ledger discrepancies and open incidents."""
        org = self.get_tenant()
        incidents = services.reconcile_inventory_integrity(organization=org, actor=request.user)
        out = InventoryReconciliationIncidentSerializer(incidents, many=True)
        return Response(
            {"incidents_found": len(incidents), "incidents": out.data},
            status=status.HTTP_200_OK,
        )

    @extend_schema(tags=["Inventory"], summary="Resolve reconciliation incident with auditable adjustment")
    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Resolve an incident and bring inventory balance into sync."""
        incident = self.get_object()
        org = self.get_tenant()
        notes = str(request.data.get("notes", "Resolved via API"))
        incident = services.resolve_reconciliation_incident(
            organization=org,
            incident=incident,
            notes=notes,
            actor=request.user,
        )
        out = InventoryReconciliationIncidentSerializer(incident)
        return Response(out.data, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List stock levels across warehouses and locations"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve stock level for warehouse item"),
)
class StockLevelViewSet(TenantScopedModelViewSet):
    """API endpoint for inspecting warehouse and location stock levels."""

    queryset = StockLevel.objects.select_related("product", "variant", "warehouse", "location").all()
    serializer_class = StockLevelSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
    }
    search_fields = ["product__name", "product__sku", "warehouse__name", "location__name"]
    ordering_fields = ["product__name", "on_hand", "avg_cost"]
    ordering = ["product__name"]


@extend_schema_view(
    list=extend_schema(tags=["Inventory"], summary="List stock movement ledger entries"),
    retrieve=extend_schema(tags=["Inventory"], summary="Retrieve stock movement entry"),
)
class StockMovementViewSet(TenantScopedModelViewSet):
    """API endpoint for reading the immutable stock movement ledger."""

    queryset = StockMovement.objects.select_related(
        "product", "variant", "warehouse", "location", "destination_location"
    ).all()
    serializer_class = StockMovementSerializer
    lookup_field = "public_id"
    module_key = "inventory"
    permission_map = {
        "list": "inventory.view",
        "retrieve": "inventory.view",
    }
    search_fields = [
        "product__name",
        "product__sku",
        "warehouse__name",
        "location__name",
        "reference_type",
        "reference_id",
    ]
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
            "source_location",
            "destination_location",
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
        "submit_transfer": "inventory.transfer",
        "approve_transfer": "inventory.transfer",
        "reject_transfer": "inventory.transfer",
        "dispatch_transfer": "inventory.transfer",
        "receive_transfer": "inventory.transfer",
        "cancel_transfer": "inventory.transfer",
    }
    search_fields = ["transfer_number", "notes", "carrier", "tracking_number"]
    ordering_fields = ["created_at", "transfer_number"]
    ordering = ["-created_at"]

    @extend_schema(tags=["Inventory"], summary="Submit stock transfer for managerial approval")
    @action(detail=True, methods=["post"], url_path="submit")
    def submit_transfer(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Submit draft stock transfer for approval."""
        transfer = self.get_object()
        org = self.get_tenant()
        transfer = services.submit_stock_transfer(organization=org, transfer=transfer, actor=request.user)
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Inventory"], summary="Approve pending stock transfer")
    @action(detail=True, methods=["post"], url_path="approve")
    def approve_transfer(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Approve a stock transfer."""
        transfer = self.get_object()
        org = self.get_tenant()
        transfer = services.approve_stock_transfer(organization=org, transfer=transfer, actor=request.user)
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Inventory"], summary="Reject pending stock transfer")
    @action(detail=True, methods=["post"], url_path="reject")
    def reject_transfer(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Reject a pending stock transfer."""
        transfer = self.get_object()
        org = self.get_tenant()
        reason = str(request.data.get("reason", "Rejected via API"))
        transfer = services.reject_stock_transfer(
            organization=org, transfer=transfer, reason=reason, actor=request.user
        )
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Inventory"], summary="Dispatch approved stock transfer into transit")
    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_transfer(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Dispatch a stock transfer into transit."""
        transfer = self.get_object()
        org = self.get_tenant()
        carrier = str(request.data.get("carrier", ""))
        tracking_number = str(request.data.get("tracking_number", ""))
        transfer = services.dispatch_stock_transfer(
            organization=org,
            transfer=transfer,
            carrier=carrier,
            tracking_number=tracking_number,
            actor=request.user,
        )
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Inventory"], summary="Receive in-transit stock transfer at destination warehouse")
    @action(detail=True, methods=["post"], url_path="receive")
    def receive_transfer(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Receive an in-transit stock transfer at the destination warehouse."""
        transfer = self.get_object()
        org = self.get_tenant()
        receipt_lines = request.data.get("receipt_lines")
        transfer = services.receive_stock_transfer(
            organization=org,
            transfer=transfer,
            receipt_lines=receipt_lines,
            actor=request.user,
        )
        serializer = self.get_serializer(transfer)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(tags=["Inventory"], summary="Cancel a stock transfer")
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_transfer(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Cancel a stock transfer before dispatch."""
        transfer = self.get_object()
        org = self.get_tenant()
        reason = str(request.data.get("reason", "Cancelled via API"))
        transfer = services.cancel_stock_transfer(
            organization=org, transfer=transfer, reason=reason, actor=request.user
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

    queryset = (
        StockAdjustment.objects.select_related("warehouse", "location")
        .prefetch_related("lines__product")
        .all()
    )
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

__all__ = [
    "InventoryLocationViewSet",
    "InventoryReconciliationViewSet",
    "StockAdjustmentViewSet",
    "StockLevelViewSet",
    "StockMovementViewSet",
    "StockReservationViewSet",
    "StockSupplyRouteViewSet",
    "StockTransferViewSet",
]
