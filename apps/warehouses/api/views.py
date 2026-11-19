"""REST API viewsets for Warehouses, Branch Allocations, Locations, and Supply Routes."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.api.viewsets import TenantScopedModelViewSet
from apps.inventory.models import InventoryLocation, StockSupplyRoute
from apps.tenancy.models import Branch
from apps.warehouses import selectors, services
from apps.warehouses.api.serializers import (
    BranchWarehouseCreateSerializer,
    BranchWarehouseSerializer,
    InventoryLocationCreateSerializer,
    InventoryLocationSerializer,
    StockSupplyRouteCreateSerializer,
    StockSupplyRouteSerializer,
    WarehouseCreateSerializer,
    WarehouseLinkBranchSerializer,
    WarehouseSerializer,
    WarehouseUnlinkBranchSerializer,
)
from apps.warehouses.models import (
    BranchWarehouse,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseType,
)


@extend_schema_view(
    list=extend_schema(tags=["Warehouses"], summary="List warehouse storage facilities"),
    retrieve=extend_schema(tags=["Warehouses"], summary="Retrieve warehouse details"),
    create=extend_schema(tags=["Warehouses"], summary="Create warehouse facility"),
    update=extend_schema(tags=["Warehouses"], summary="Update warehouse facility"),
    partial_update=extend_schema(tags=["Warehouses"], summary="Partially update warehouse facility"),
    destroy=extend_schema(tags=["Warehouses"], summary="Delete warehouse facility"),
)
class WarehouseViewSet(TenantScopedModelViewSet):
    """API endpoint for managing warehouse storage facilities."""

    queryset = Warehouse.objects.select_related("branch").all()
    serializer_class = WarehouseSerializer
    lookup_field = "public_id"
    module_key = "warehouses"
    permission_map = {
        "list": "warehouses.view",
        "retrieve": "warehouses.view",
        "create": "warehouses.manage",
        "update": "warehouses.manage",
        "partial_update": "warehouses.manage",
        "destroy": "warehouses.manage",
        "link_branch": "warehouses.manage",
        "unlink_branch": "warehouses.manage",
    }
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]
    ordering = ["name"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        wh_type = self.request.query_params.get("warehouse_type")
        if wh_type:
            qs = qs.filter(warehouse_type=wh_type)
        return qs

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Create a new warehouse facility."""
        serializer = WarehouseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org = self.get_tenant()

        branch = None
        if data.get("branch_id"):
            branch = Branch.all_tenants.filter(organization=org, public_id=data["branch_id"]).first()
            if not branch:
                return Response(
                    {"error": "invalid_branch", "message": "Branch not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            wh = services.create_warehouse(
                organization=org,
                name=str(data["name"]),
                warehouse_type=str(data.get("warehouse_type", WarehouseType.PRIMARY)),
                branch=branch,
                code=str(data.get("code", "")),
                is_central=bool(data.get("is_central", False)),
                is_default=bool(data.get("is_default", False)),
                can_sell=bool(data.get("can_sell", True)),
                can_replenish=bool(data.get("can_replenish", True)),
                priority=int(data.get("priority", 1)),
                actor=request.user,
            )
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response(
                {"error": "validation_error", "message": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out = WarehouseSerializer(wh)
        return Response(out.data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Delete a warehouse facility."""
        wh = self.get_object()
        services.delete_warehouse(warehouse=wh, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=["Warehouses"],
        summary="Authorize branch to fulfill from or link to this warehouse",
        request=WarehouseLinkBranchSerializer,
        responses={200: BranchWarehouseSerializer},
    )
    @action(detail=True, methods=["post"], url_path="link-branch")
    def link_branch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        wh = self.get_object()
        org = self.get_tenant()
        serializer = WarehouseLinkBranchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        branch = Branch.all_tenants.filter(organization=org, public_id=data["branch_id"]).first()
        if not branch:
            return Response(
                {"error": "invalid_branch", "message": "Branch not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rel_type = data.get("relationship_type", BranchWarehouseRelationshipType.LINKED_SUPPLY)
        try:
            if rel_type == BranchWarehouseRelationshipType.SYNCHRONIZED:
                mapping = services.add_synchronized_branch(
                    organization=org,
                    warehouse=wh,
                    branch=branch,
                    actor=request.user,
                )
            elif rel_type == BranchWarehouseRelationshipType.LINKED_SUPPLY:
                mapping = services.add_linked_branch(
                    organization=org,
                    warehouse=wh,
                    branch=branch,
                    actor=request.user,
                )
            else:
                mapping = services.link_warehouse_to_branch(
                    organization=org,
                    branch=branch,
                    warehouse=wh,
                    is_default=bool(data.get("is_default", False)),
                    can_sell=bool(data.get("can_sell", True)),
                    can_replenish=bool(data.get("can_replenish", True)),
                    priority=int(data.get("priority", 1)),
                    actor=request.user,
                )
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response(
                {"error": "validation_error", "message": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out = BranchWarehouseSerializer(mapping)
        return Response(out.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Warehouses"],
        summary="Unlink a branch relationship from this warehouse",
        request=WarehouseUnlinkBranchSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], url_path="unlink-branch")
    def unlink_branch(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        wh = self.get_object()
        org = self.get_tenant()
        serializer = WarehouseUnlinkBranchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        branch = Branch.all_tenants.filter(organization=org, public_id=data["branch_id"]).first()
        if not branch:
            return Response(
                {"error": "invalid_branch", "message": "Branch not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rel_type = data.get("relationship_type")
        try:
            if rel_type:
                services.remove_branch_relationship(
                    organization=org,
                    warehouse=wh,
                    branch=branch,
                    relationship_type=rel_type,
                    actor=request.user,
                )
            else:
                services.unlink_warehouse_from_branch(
                    organization=org,
                    branch=branch,
                    warehouse=wh,
                    actor=request.user,
                )
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response(
                {"error": "validation_error", "message": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(tags=["Warehouses"], summary="List branch fulfillment warehouse mappings"),
    retrieve=extend_schema(tags=["Warehouses"], summary="Retrieve branch warehouse mapping"),
    create=extend_schema(tags=["Warehouses"], summary="Create branch warehouse mapping"),
)
class BranchWarehouseViewSet(TenantScopedModelViewSet):
    """API endpoint for querying branch-warehouse fulfillment matrix."""

    queryset = BranchWarehouse.objects.select_related("branch", "warehouse").all()
    serializer_class = BranchWarehouseSerializer
    lookup_field = "public_id"
    module_key = "warehouses"
    permission_map = {
        "list": "warehouses.view",
        "retrieve": "warehouses.view",
        "create": "warehouses.manage",
        "destroy": "warehouses.manage",
    }
    ordering = ["branch__name", "priority"]

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        rel_type = self.request.query_params.get("relationship_type")
        if rel_type:
            qs = qs.filter(relationship_type=rel_type)
        return qs

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Create a branch-warehouse fulfillment or supply mapping."""
        serializer = BranchWarehouseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org = self.get_tenant()

        branch = Branch.all_tenants.filter(organization=org, public_id=data["branch_id"]).first()
        if not branch:
            return Response(
                {"error": "invalid_branch", "message": "Branch not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wh = Warehouse.all_tenants.filter(organization=org, public_id=data["warehouse_id"]).first()
        if not wh:
            return Response(
                {"error": "invalid_warehouse", "message": "Warehouse not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rel_type = data.get("relationship_type", BranchWarehouseRelationshipType.LINKED_SUPPLY)
        try:
            if rel_type == BranchWarehouseRelationshipType.SYNCHRONIZED:
                mapping = services.add_synchronized_branch(
                    organization=org,
                    warehouse=wh,
                    branch=branch,
                    actor=request.user,
                )
            elif rel_type == BranchWarehouseRelationshipType.LINKED_SUPPLY:
                mapping = services.add_linked_branch(
                    organization=org,
                    warehouse=wh,
                    branch=branch,
                    actor=request.user,
                )
            else:
                mapping = services.link_warehouse_to_branch(
                    organization=org,
                    branch=branch,
                    warehouse=wh,
                    is_default=bool(data.get("is_default", False)),
                    can_sell=bool(data.get("can_sell", True)),
                    can_replenish=bool(data.get("can_replenish", True)),
                    priority=int(data.get("priority", 1)),
                    actor=request.user,
                )
        except ValidationError as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            return Response(
                {"error": "validation_error", "message": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )

        out = BranchWarehouseSerializer(mapping)
        return Response(out.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(tags=["Warehouses"], summary="List inventory storage locations"),
    retrieve=extend_schema(tags=["Warehouses"], summary="Retrieve inventory location details"),
    create=extend_schema(tags=["Warehouses"], summary="Create inventory location"),
    update=extend_schema(tags=["Warehouses"], summary="Update inventory location"),
    partial_update=extend_schema(tags=["Warehouses"], summary="Partially update inventory location"),
    destroy=extend_schema(tags=["Warehouses"], summary="Delete inventory location"),
)
class InventoryLocationViewSet(TenantScopedModelViewSet):
    """API endpoint for managing inventory locations and warehouse hierarchy."""

    queryset = InventoryLocation.objects.select_related("parent", "branch", "warehouse").all()
    serializer_class = InventoryLocationSerializer
    lookup_field = "public_id"
    module_key = "warehouses"
    permission_map = {
        "list": "warehouses.view",
        "retrieve": "warehouses.view",
        "hierarchy": "warehouses.view",
        "create": "warehouses.manage",
        "update": "warehouses.manage",
        "partial_update": "warehouses.manage",
        "destroy": "warehouses.manage",
    }
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code", "created_at"]
    ordering = ["name"]

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Create a new inventory location."""
        serializer = InventoryLocationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org = self.get_tenant()

        parent = None
        if data.get("parent_id"):
            parent = InventoryLocation.all_tenants.filter(organization=org, public_id=data["parent_id"]).first()

        branch = None
        if data.get("branch_id"):
            branch = Branch.all_tenants.filter(organization=org, public_id=data["branch_id"]).first()

        warehouse = None
        if data.get("warehouse_id"):
            warehouse = Warehouse.all_tenants.filter(organization=org, public_id=data["warehouse_id"]).first()

        loc = services.create_inventory_location(
            organization=org,
            name=str(data["name"]),
            code=str(data.get("code", "")),
            location_type=str(data.get("location_type", "branch_warehouse")),
            parent=parent,
            branch=branch,
            warehouse=warehouse,
            is_stock_holding=bool(data.get("is_stock_holding", True)),
            address=str(data.get("address", "")),
            notes=str(data.get("notes", "")),
            actor=request.user,
        )
        out = InventoryLocationSerializer(loc)
        return Response(out.data, status=status.HTTP_201_CREATED)

    def destroy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Delete an inventory location."""
        location = self.get_object()
        services.delete_inventory_location(
            location=location,
            actor=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["Warehouses"], summary="Retrieve complete location tree hierarchy")
    @action(detail=False, methods=["get"], url_path="hierarchy")
    def hierarchy(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Return the nested parent-child location tree."""
        org = self.get_tenant()
        tree = selectors.get_location_hierarchy(organization=org)
        return Response(tree, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(tags=["Warehouses"], summary="List stock supply routes"),
    retrieve=extend_schema(tags=["Warehouses"], summary="Retrieve stock supply route details"),
    create=extend_schema(tags=["Warehouses"], summary="Create stock supply route"),
    destroy=extend_schema(tags=["Warehouses"], summary="Delete stock supply route"),
)
class StockSupplyRouteViewSet(TenantScopedModelViewSet):
    """API endpoint for M:N stock supply and replenishment routes."""

    queryset = StockSupplyRoute.objects.select_related("source_location", "destination_location").all()
    serializer_class = StockSupplyRouteSerializer
    lookup_field = "public_id"
    module_key = "warehouses"
    permission_map = {
        "list": "warehouses.view",
        "retrieve": "warehouses.view",
        "create": "warehouses.manage",
        "destroy": "warehouses.manage",
    }
    ordering_fields = ["priority", "created_at"]
    ordering = ["destination_location__name", "priority"]

    def create(self, request: Any, *args: Any, **kwargs: Any) -> Response:
        """Create a new stock supply route."""
        serializer = StockSupplyRouteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org = self.get_tenant()

        src = InventoryLocation.all_tenants.filter(
            organization=org, public_id=data["source_location_id"]
        ).first()
        dest = InventoryLocation.all_tenants.filter(
            organization=org, public_id=data["destination_location_id"]
        ).first()

        if not src or not dest:
            return Response(
                {"error": "invalid_locations", "message": "Source or destination location not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        route = services.create_supply_route(
            organization=org,
            source_location=src,
            destination_location=dest,
            priority=int(data.get("priority", 1)),
            is_preferred=bool(data.get("is_preferred", False)),
            lead_time_days=int(data.get("lead_time_days", 0)),
            can_auto_replenish=bool(data.get("can_auto_replenish", False)),
            notes=str(data.get("notes", "")),
            actor=request.user,
        )
        out = StockSupplyRouteSerializer(route)
        return Response(out.data, status=status.HTTP_201_CREATED)
