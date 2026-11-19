"""REST API serializers for Warehouses, Branch Allocations, Locations, and Supply Routes."""

from __future__ import annotations

from rest_framework import serializers

from apps.inventory.models import InventoryLocation, LocationType, StockSupplyRoute
from apps.warehouses.models import (
    BranchWarehouse,
    BranchWarehouseRelationshipType,
    Warehouse,
    WarehouseType,
)


class WarehouseSerializer(serializers.ModelSerializer[Warehouse]):
    """Serializer for warehouse storage facilities."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    branch_id = serializers.UUIDField(source="branch.public_id", read_only=True, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, allow_null=True)
    operational_branch_id = serializers.UUIDField(source="branch.public_id", read_only=True, allow_null=True)
    operational_branch_name = serializers.CharField(source="branch.name", read_only=True, allow_null=True)
    warehouse_type = serializers.CharField()
    warehouse_type_display = serializers.CharField(source="get_warehouse_type_display", read_only=True)
    is_primary = serializers.BooleanField(read_only=True)
    is_secondary = serializers.BooleanField(read_only=True)
    synchronized_branches = serializers.SerializerMethodField()
    linked_branches = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "name",
            "code",
            "warehouse_type",
            "warehouse_type_display",
            "branch_id",
            "branch_name",
            "operational_branch_id",
            "operational_branch_name",
            "is_primary",
            "is_secondary",
            "is_central",
            "is_default",
            "is_active",
            "synchronized_branches",
            "linked_branches",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "branch_id",
            "branch_name",
            "operational_branch_id",
            "operational_branch_name",
            "warehouse_type_display",
            "is_primary",
            "is_secondary",
            "synchronized_branches",
            "linked_branches",
            "created_at",
            "updated_at",
        ]

    def get_synchronized_branches(self, obj: Warehouse) -> list[dict[str, str]]:
        from apps.warehouses import selectors  # noqa: PLC0415
        branches = selectors.list_synchronized_branches_for_warehouse(warehouse=obj)
        return [{"id": str(b.public_id), "name": b.name, "code": b.code} for b in branches]

    def get_linked_branches(self, obj: Warehouse) -> list[dict[str, str]]:
        from apps.warehouses import selectors  # noqa: PLC0415
        branches = selectors.list_linked_branches_for_warehouse(warehouse=obj)
        return [{"id": str(b.public_id), "name": b.name, "code": b.code} for b in branches]


class WarehouseCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Input serializer for creating or updating a warehouse facility."""

    name = serializers.CharField(max_length=128)
    code = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    warehouse_type = serializers.ChoiceField(
        choices=WarehouseType.choices,
        default=WarehouseType.PRIMARY,
        required=False,
    )
    branch_id = serializers.UUIDField(required=False, allow_null=True)
    is_central = serializers.BooleanField(default=False)
    is_default = serializers.BooleanField(default=False)
    is_active = serializers.BooleanField(default=True)
    can_sell = serializers.BooleanField(default=True)
    can_replenish = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(default=1, min_value=1)


class WarehouseLinkBranchSerializer(serializers.Serializer[dict[str, object]]):
    """Input serializer for linking a branch to a warehouse."""

    branch_id = serializers.UUIDField()
    relationship_type = serializers.ChoiceField(
        choices=BranchWarehouseRelationshipType.choices,
        default=BranchWarehouseRelationshipType.LINKED_SUPPLY,
        required=False,
    )
    is_default = serializers.BooleanField(default=False)
    can_sell = serializers.BooleanField(default=True)
    can_replenish = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(default=1, min_value=1)


class WarehouseUnlinkBranchSerializer(serializers.Serializer[dict[str, object]]):
    """Input serializer for unlinking a branch from a warehouse."""

    branch_id = serializers.UUIDField()
    relationship_type = serializers.ChoiceField(
        choices=BranchWarehouseRelationshipType.choices,
        required=False,
        allow_null=True,
    )


class BranchWarehouseSerializer(serializers.ModelSerializer[BranchWarehouse]):
    """Serializer for branch-to-warehouse fulfillment mapping."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    branch_id = serializers.UUIDField(source="branch.public_id", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True)
    warehouse_id = serializers.UUIDField(source="warehouse.public_id", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    relationship_type = serializers.CharField(read_only=True)
    relationship_type_display = serializers.CharField(source="get_relationship_type_display", read_only=True)

    class Meta:
        model = BranchWarehouse
        fields = [
            "id",
            "branch_id",
            "branch_name",
            "warehouse_id",
            "warehouse_name",
            "relationship_type",
            "relationship_type_display",
            "is_default",
            "can_sell",
            "can_replenish",
            "is_storage_synced",
            "priority",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "branch_id",
            "branch_name",
            "warehouse_id",
            "warehouse_name",
            "relationship_type",
            "relationship_type_display",
            "created_at",
            "updated_at",
        ]


class BranchWarehouseCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Input serializer for linking a warehouse to a branch."""

    branch_id = serializers.UUIDField()
    warehouse_id = serializers.UUIDField()
    relationship_type = serializers.ChoiceField(
        choices=BranchWarehouseRelationshipType.choices,
        default=BranchWarehouseRelationshipType.LINKED_SUPPLY,
        required=False,
    )
    is_default = serializers.BooleanField(default=False)
    can_sell = serializers.BooleanField(default=True)
    can_replenish = serializers.BooleanField(default=True)
    priority = serializers.IntegerField(default=1, min_value=1)


class InventoryLocationSerializer(serializers.ModelSerializer[InventoryLocation]):
    """Serializer for inventory locations and warehouse hierarchy nodes."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    parent_id = serializers.UUIDField(source="parent.public_id", read_only=True, allow_null=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True, allow_null=True)
    branch_id = serializers.UUIDField(source="branch.public_id", read_only=True, allow_null=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, allow_null=True)
    warehouse_id = serializers.UUIDField(source="warehouse.public_id", read_only=True, allow_null=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True, allow_null=True)

    class Meta:
        model = InventoryLocation
        fields = [
            "id",
            "name",
            "code",
            "location_type",
            "parent_id",
            "parent_name",
            "branch_id",
            "branch_name",
            "warehouse_id",
            "warehouse_name",
            "full_path",
            "is_stock_holding",
            "is_active",
            "address",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "parent_id",
            "parent_name",
            "branch_id",
            "branch_name",
            "warehouse_id",
            "warehouse_name",
            "full_path",
            "created_at",
            "updated_at",
        ]


class InventoryLocationCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Input serializer for creating an inventory location."""

    name = serializers.CharField(max_length=255)
    code = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    location_type = serializers.ChoiceField(choices=LocationType.choices, default=LocationType.BRANCH_WAREHOUSE)
    parent_id = serializers.UUIDField(required=False, allow_null=True)
    branch_id = serializers.UUIDField(required=False, allow_null=True)
    warehouse_id = serializers.UUIDField(required=False, allow_null=True)
    is_stock_holding = serializers.BooleanField(default=True)
    address = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class StockSupplyRouteSerializer(serializers.ModelSerializer[StockSupplyRoute]):
    """Serializer for M:N stock replenishment supply routes."""

    id = serializers.UUIDField(source="public_id", read_only=True)
    source_location_id = serializers.UUIDField(source="source_location.public_id", read_only=True)
    source_location_name = serializers.CharField(source="source_location.name", read_only=True)
    destination_location_id = serializers.UUIDField(source="destination_location.public_id", read_only=True)
    destination_location_name = serializers.CharField(source="destination_location.name", read_only=True)

    class Meta:
        model = StockSupplyRoute
        fields = [
            "id",
            "source_location_id",
            "source_location_name",
            "destination_location_id",
            "destination_location_name",
            "priority",
            "is_preferred",
            "lead_time_days",
            "can_auto_replenish",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "source_location_id",
            "source_location_name",
            "destination_location_id",
            "destination_location_name",
            "created_at",
            "updated_at",
        ]


class StockSupplyRouteCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Input serializer for defining a stock supply route."""

    source_location_id = serializers.UUIDField()
    destination_location_id = serializers.UUIDField()
    priority = serializers.IntegerField(default=1, min_value=1)
    is_preferred = serializers.BooleanField(default=False)
    lead_time_days = serializers.IntegerField(default=0, min_value=0)
    can_auto_replenish = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
