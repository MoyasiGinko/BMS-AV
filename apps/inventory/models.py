"""Inventory data models: ledger, stock levels, transfers, adjustments, and counts."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class MovementType(models.TextChoices):
    RECEIPT = "receipt", _("Receipt")
    ISSUE = "issue", _("Issue")
    TRANSFER_IN = "transfer_in", _("Transfer In")
    TRANSFER_OUT = "transfer_out", _("Transfer Out")
    ADJUSTMENT_IN = "adjustment_in", _("Adjustment In")
    ADJUSTMENT_OUT = "adjustment_out", _("Adjustment Out")
    RETURN_IN = "return_in", _("Return In")
    RETURN_OUT = "return_out", _("Return Out")


class StorageType(models.TextChoices):
    SELLABLE = "sellable", _("Sellable Products (Outlets)")
    INTERNAL_USE = "internal_use", _("Goods & Ingredients (Not for Sale)")


class LocationType(models.TextChoices):
    PRIMARY_WAREHOUSE = "primary_warehouse", _("Primary Warehouse")
    SECONDARY_WAREHOUSE = "secondary_warehouse", _("Secondary Warehouse")
    CENTRAL_WAREHOUSE = "central_warehouse", _("Primary Hub")
    REGIONAL_WAREHOUSE = "regional_warehouse", _("Secondary Hub")
    BRANCH_WAREHOUSE = "branch_warehouse", _("Branch Warehouse")
    RETAIL_OUTLET = "retail_outlet", _("Retail Outlet")
    SELLABLE_STORAGE = "sellable_storage", _("Sellable Storage (Outlets)")
    INTERNAL_STORAGE = "internal_storage", _("Goods & Ingredients (Not for Sale)")
    SUB_LOCATION = "sub_location", _("Sub-Location / Bin / Shelf / Zone")
    TRANSIT = "transit", _("In-Transit Virtual Location")
    QUARANTINE = "quarantine", _("Quarantine / Inspection")
    DAMAGED = "damaged", _("Damaged Goods Storage")


class WarehouseStorageType(TenantModel):
    """Dynamic storage type configured per warehouse or organization.

    Determines storage classification, operational rules, and whether inventory
    stored under this storage type is eligible for outlet/POS sales.
    """

    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="storage_types",
        verbose_name=_("warehouse"),
        help_text=_("Associated warehouse facility. If left empty, acts as an organization-level storage type template."),
    )
    name = models.CharField(_("storage type name"), max_length=128)
    code = models.CharField(_("storage type code"), max_length=64)
    description = models.TextField(_("description"), blank=True, default="")
    can_sell = models.BooleanField(
        _("can sell products"),
        default=True,
        help_text=_("Designates whether goods in this storage type can be sold through retail outlets and POS."),
    )
    is_default_sellable = models.BooleanField(
        _("default sellable storage"),
        default=False,
        help_text=_("Primary storage type used for outlet sales from this warehouse."),
    )
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("warehouse storage type")
        verbose_name_plural = _("warehouse storage types")
        ordering = ["-is_default_sellable", "-can_sell", "name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "warehouse", "code"],
                name="unique_org_warehouse_storage_type_code",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "warehouse", "can_sell"]),
        ]

    def __str__(self) -> str:
        wh_name = self.warehouse.name if self.warehouse else "Org Default"
        sell_badge = "Sellable" if self.can_sell else "Internal Only"
        return f"{self.name} ({wh_name}) - {sell_badge}"


class BranchStorageSync(TenantModel):
    """Bridge linking a branch warehouse mapping to specific synced warehouse storage types."""

    branch_warehouse = models.ForeignKey(
        "tenancy.BranchWarehouse",
        on_delete=models.CASCADE,
        related_name="storage_sync_links",
        verbose_name=_("branch warehouse mapping"),
    )
    storage_type = models.ForeignKey(
        "inventory.WarehouseStorageType",
        on_delete=models.CASCADE,
        related_name="branch_sync_links",
        verbose_name=_("synced warehouse storage type"),
    )
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("branch warehouse storage sync")
        verbose_name_plural = _("branch warehouse storage syncs")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "branch_warehouse", "storage_type"],
                name="unique_org_branch_wh_storage_sync",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "branch_warehouse", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.branch_warehouse} -> {self.storage_type.name}"


class InventoryLocation(TenantModel):
    """Unified location entity supporting warehouses, branches, retail outlets, zones, bins."""

    name = models.CharField(_("name"), max_length=255)
    code = models.CharField(_("location code"), max_length=64, blank=True, default="")
    location_type = models.CharField(
        _("location type"),
        max_length=32,
        choices=LocationType.choices,
        default=LocationType.BRANCH_WAREHOUSE,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("parent location"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_locations",
        verbose_name=_("branch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_locations",
        verbose_name=_("linked warehouse"),
    )
    storage_type = models.CharField(
        _("storage type"),
        max_length=64,
        choices=StorageType.choices,
        default=StorageType.SELLABLE,
        help_text=_("Designates whether goods stored here are sellable through outlets or for internal use."),
    )
    custom_storage_type = models.ForeignKey(
        "inventory.WarehouseStorageType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_locations",
        verbose_name=_("custom storage type"),
    )
    is_stock_holding = models.BooleanField(
        _("is stock holding"),
        default=True,
        help_text=_("Designates whether products can be stored directly at this location node."),
    )
    is_active = models.BooleanField(_("is active"), default=True)
    address = models.TextField(_("physical address"), blank=True, default="")
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("inventory location")
        verbose_name_plural = _("inventory locations")
        ordering = ["name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "parent", "name"],
                name="uniq_location_org_parent_name",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "location_type"]),
            models.Index(fields=["organization", "branch"]),
            models.Index(fields=["organization", "warehouse"]),
            models.Index(fields=["organization", "custom_storage_type"]),
            models.Index(fields=["organization", "is_stock_holding", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.full_path

    @property
    def can_sell(self) -> bool:
        """Indicates if items in this location can be sold through outlets/POS."""
        if self.custom_storage_type_id:
            return bool(self.custom_storage_type.can_sell and self.custom_storage_type.is_active)
        return self.storage_type == StorageType.SELLABLE

    @property
    def full_path(self) -> str:
        names = [self.name]
        curr = self.parent
        visited = {self.id}
        while curr:
            if curr.id in visited:
                break
            visited.add(curr.id)
            names.append(curr.name)
            curr = curr.parent
        return " > ".join(reversed(names))

    def get_descendant_ids(self) -> list[int]:
        ids = [self.id]
        for child in self.children.filter(is_active=True):
            ids.extend(child.get_descendant_ids())
        return ids


class StockSupplyRoute(TenantModel):
    """Dynamic M:N supply route defining allowed replenishment from source to destination."""

    source_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.CASCADE,
        related_name="outbound_supply_routes",
        verbose_name=_("source location"),
    )
    destination_location = models.ForeignKey(
        InventoryLocation,
        on_delete=models.CASCADE,
        related_name="inbound_supply_routes",
        verbose_name=_("destination location"),
    )
    priority = models.PositiveSmallIntegerField(
        _("priority"),
        default=1,
        help_text=_("Order of preference (1 = primary / preferred)."),
    )
    is_preferred = models.BooleanField(
        _("is preferred route"),
        default=False,
    )
    lead_time_days = models.PositiveSmallIntegerField(
        _("lead time in days"),
        default=0,
    )
    can_auto_replenish = models.BooleanField(
        _("allow automated replenishment"),
        default=False,
    )
    is_active = models.BooleanField(
        _("is active"),
        default=True,
    )
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock supply route")
        verbose_name_plural = _("stock supply routes")
        ordering = ["destination_location", "priority"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "source_location", "destination_location"],
                name="uniq_supply_route_org_src_dst",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "destination_location", "priority"]),
            models.Index(fields=["organization", "source_location"]),
        ]

    def __str__(self) -> str:
        preferred = " [Preferred]" if self.is_preferred else ""
        return f"{self.source_location.name} -> {self.destination_location.name} (P{self.priority}){preferred}"


class AdjustmentReason(models.TextChoices):
    DAMAGE = "damage", _("Damaged Goods")
    SPOILAGE = "spoilage", _("Spoilage / Expiry")
    SHRINKAGE = "shrinkage", _("Shrinkage / Theft")
    COUNT_VARIANCE = "count_variance", _("Cycle Count Variance")
    CORRECTION = "correction", _("Correction / Other")
    IN_TRANSIT_LOSS = "in_transit_loss", _("In-Transit Loss / Damage")
    RETURN_INSPECTION_SCRAP = "return_inspection_scrap", _("Return Inspection Scrap")
    RECONCILIATION_VARIANCE = "reconciliation_variance", _("Reconciliation Variance")


class TransferStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_APPROVAL = "pending_approval", _("Pending Approval")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    DISPATCHED = "dispatched", _("Dispatched")
    IN_TRANSIT = "in_transit", _("In Transit")
    PARTIALLY_RECEIVED = "partially_received", _("Partially Received")
    RECEIVED = "received", _("Received")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class TransferType(models.TextChoices):
    REQUISITION = "requisition", _("Stock Requisition")
    RETURN = "return", _("Stock Return")
    REPLACEMENT = "replacement", _("Stock Replacement")
    INTERNAL = "internal", _("Internal Transfer")
    PUSH_DISTRIBUTION = "push_distribution", _("Warehouse Push Distribution")
    INTER_BRANCH = "inter_branch", _("Inter-Branch Transfer")


class CountStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    IN_PROGRESS = "in_progress", _("In Progress")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class ReservationStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    FULFILLED = "fulfilled", _("Fulfilled")
    RELEASED = "released", _("Released")
    EXPIRED = "expired", _("Expired")


class StockLevel(TenantModel):
    """Cached current stock level, reservations, and average cost per warehouse item."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="stock_levels",
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stock_levels",
        verbose_name=_("product variant"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.CASCADE,
        related_name="stock_levels",
        verbose_name=_("warehouse"),
    )
    location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stock_levels",
        verbose_name=_("inventory location"),
    )
    on_hand = models.DecimalField(
        _("on hand quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    reserved = models.DecimalField(
        _("reserved quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    in_transit = models.DecimalField(
        _("in-transit quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    avg_cost = models.DecimalField(
        _("weighted average cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    reorder_point = models.DecimalField(
        _("reorder point"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )
    reorder_quantity = models.DecimalField(
        _("reorder quantity"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock level")
        verbose_name_plural = _("stock levels")
        ordering = ["product__name"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "warehouse", "product", "variant"],
                name="uniq_stocklevel_org_wh_prod_var",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "warehouse", "product"]),
            models.Index(fields=["organization", "location", "product"]),
            models.Index(fields=["organization", "on_hand"]),
            models.Index(fields=["organization", "in_transit"]),
        ]

    def __str__(self) -> str:
        var_text = f" ({self.variant.name})" if self.variant else ""
        return f"{self.product.name}{var_text} @ {self.warehouse.name}: {self.on_hand}"

    @property
    def available(self) -> Decimal:
        """Physical on-hand less active reservations."""
        return max(Decimal("0.0000"), self.on_hand - self.reserved)

    @property
    def total_value(self) -> Decimal:
        """Total inventory asset value for this item in this warehouse."""
        return (self.on_hand * self.avg_cost).quantize(Decimal("0.0001"))

    @property
    def is_low_stock(self) -> bool:
        if self.reorder_point is not None:
            return self.available <= self.reorder_point
        if self.product.reorder_level is not None:
            return self.available <= self.product.reorder_level
        return False


class StockMovement(TenantModel):
    """Immutable ledger record of any physical stock change."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("product variant"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="stock_movements",
        verbose_name=_("warehouse"),
    )
    location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("inventory location"),
    )
    destination_location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="inbound_stock_movements",
        verbose_name=_("destination location"),
    )
    type = models.CharField(
        _("movement type"),
        max_length=32,
        choices=MovementType.choices,
    )
    quantity = models.DecimalField(
        _("quantity change"),
        max_digits=18,
        decimal_places=4,
    )
    unit_cost = models.DecimalField(
        _("unit cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cost = models.DecimalField(
        _("total cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    reference_type = models.CharField(
        _("reference type"),
        max_length=64,
        blank=True,
        default="",
    )
    reference_id = models.CharField(
        _("reference ID"),
        max_length=64,
        blank=True,
        default="",
    )
    occurred_at = models.DateTimeField(
        _("occurred at"),
        default=timezone.now,
    )
    notes = models.CharField(
        _("notes"),
        max_length=255,
        blank=True,
        default="",
    )
    batch = models.ForeignKey(
        "inventory.Batch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movements",
        verbose_name=_("batch"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-occurred_at", "-id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "warehouse", "product", "-occurred_at"]),
            models.Index(fields=["organization", "location", "product", "-occurred_at"]),
            models.Index(fields=["organization", "reference_type", "reference_id"]),
            models.Index(fields=["organization", "type", "-occurred_at"]),
            models.Index(fields=["organization", "batch"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.quantity > Decimal("0") else ""
        return (
            f"{self.occurred_at:%Y-%m-%d} [{self.get_type_display()}]: "
            f"{self.product.name} ({sign}{self.quantity})"
        )


class StockReservation(TenantModel):
    """Allocation of stock to prevent overselling before actual issue."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="stock_reservations",
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_reservations",
        verbose_name=_("product variant"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="stock_reservations",
        verbose_name=_("warehouse"),
    )
    quantity = models.DecimalField(
        _("reserved quantity"),
        max_digits=18,
        decimal_places=4,
    )
    reference_type = models.CharField(
        _("reference type"),
        max_length=64,
        blank=True,
        default="",
    )
    reference_id = models.CharField(
        _("reference ID"),
        max_length=64,
        blank=True,
        default="",
    )
    status = models.CharField(
        _("reservation status"),
        max_length=32,
        choices=ReservationStatus.choices,
        default=ReservationStatus.ACTIVE,
    )
    expires_at = models.DateTimeField(
        _("expires at"),
        null=True,
        blank=True,
    )
    notes = models.CharField(
        _("notes"),
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock reservation")
        verbose_name_plural = _("stock reservations")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "status", "expires_at"]),
            models.Index(fields=["organization", "warehouse", "product"]),
        ]

    def __str__(self) -> str:
        return f"Reserve {self.quantity} x {self.product.name} ({self.get_status_display()})"


class StockTransfer(TenantModel):
    """Document moving stock between two warehouses."""

    transfer_number = models.CharField(_("transfer number"), max_length=64)
    source_warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="transfers_out",
        verbose_name=_("source warehouse"),
    )
    destination_warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="transfers_in",
        verbose_name=_("destination warehouse"),
    )
    source_location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transfers_out",
        verbose_name=_("source location"),
    )
    destination_location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transfers_in",
        verbose_name=_("destination location"),
    )
    source_branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.PROTECT,
        related_name="transfers_from",
        null=True,
        blank=True,
        verbose_name=_("source branch"),
    )
    destination_branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.PROTECT,
        related_name="transfers_to",
        null=True,
        blank=True,
        verbose_name=_("destination branch"),
    )
    is_inter_branch = models.BooleanField(
        _("is inter-branch transfer"),
        default=False,
    )
    transfer_intent = models.CharField(
        _("transfer intent"),
        max_length=16,
        blank=True,
        default="",
        help_text=_("Inter-branch transfer intent: send (outbound dispatch) or request (inbound requisition)."),
    )
    is_branch_requisition = models.BooleanField(
        _("is branch requisition"),
        default=False,
        help_text=_("Stock request initiated by a branch/outlet to a linked warehouse."),
    )
    transfer_type = models.CharField(
        _("transfer type"),
        max_length=32,
        choices=TransferType.choices,
        default=TransferType.REQUISITION,
    )
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=TransferStatus.choices,
        default=TransferStatus.DRAFT,
    )
    notes = models.TextField(_("notes"), blank=True, default="")
    tracking_number = models.CharField(
        _("tracking / consignment number"),
        max_length=128,
        blank=True,
        default="",
    )
    carrier = models.CharField(
        _("carrier / driver"),
        max_length=128,
        blank=True,
        default="",
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_stock_transfers",
        verbose_name=_("approved by"),
    )
    rejected_at = models.DateTimeField(_("rejected at"), null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_stock_transfers",
        verbose_name=_("rejected by"),
    )
    rejection_reason = models.TextField(_("rejection reason"), blank=True, default="")
    dispatched_at = models.DateTimeField(_("dispatched at"), null=True, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dispatched_stock_transfers",
        verbose_name=_("dispatched by"),
    )
    received_at = models.DateTimeField(_("received at"), null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_stock_transfers",
        verbose_name=_("received by"),
    )
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    is_push_distribution = models.BooleanField(
        _("is push distribution"),
        default=False,
        help_text=_("Stock push initiated directly by warehouse to branch outlet without prior request."),
    )
    outlet_decision = models.CharField(
        _("outlet decision"),
        max_length=32,
        blank=True,
        default="",
        help_text=_("Outlet review decision: accepted, partial_accept, returned_now, held_return_later, cancelled_returned."),
    )
    outlet_decision_notes = models.TextField(
        _("outlet decision notes"),
        blank=True,
        default="",
    )
    outlet_decision_at = models.DateTimeField(
        _("outlet decision at"),
        null=True,
        blank=True,
    )
    outlet_decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="push_transfer_decisions",
        verbose_name=_("outlet decision by"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock transfer")
        verbose_name_plural = _("stock transfers")
        ordering = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "transfer_number"],
                name="uniq_transfer_org_number",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "source_branch", "destination_branch"]),
            models.Index(fields=["organization", "is_inter_branch"]),
            models.Index(fields=["organization", "is_branch_requisition", "status"]),
            models.Index(fields=["organization", "is_push_distribution", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.transfer_number}: {self.source_warehouse.name} -> {self.destination_warehouse.name}"

    @property
    def is_in_transit(self) -> bool:
        return self.status in {
            TransferStatus.DISPATCHED,
            TransferStatus.IN_TRANSIT,
            TransferStatus.PARTIALLY_RECEIVED,
        }


class StockTransferLine(TenantModel):
    """Line item in a stock transfer."""

    transfer = models.ForeignKey(
        StockTransfer,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("transfer"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("product variant"),
    )
    quantity = models.DecimalField(
        _("quantity"),
        max_digits=18,
        decimal_places=4,
    )
    quantity_requested = models.DecimalField(
        _("quantity requested"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )
    quantity_dispatched = models.DecimalField(
        _("quantity dispatched"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    quantity_received = models.DecimalField(
        _("quantity received"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    quantity_damaged = models.DecimalField(
        _("quantity damaged"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    quantity_missing = models.DecimalField(
        _("quantity missing"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    unit_cost = models.DecimalField(
        _("unit cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    replacement_quantity = models.DecimalField(
        _("replacement quantity"),
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_("For replacement requests: quantity requested back from warehouse."),
    )
    return_reason = models.CharField(
        _("return reason"),
        max_length=64,
        blank=True,
        default="",
        help_text=_("Reason code for return (e.g. damaged, defective, expired, excess, customer_return)."),
    )
    item_condition = models.CharField(
        _("item condition"),
        max_length=64,
        blank=True,
        default="good",
        help_text=_("Condition reported by outlet (good, open_box, damaged, scrap)."),
    )
    disposition = models.CharField(
        _("warehouse disposition"),
        max_length=64,
        blank=True,
        default="",
        help_text=_("Warehouse disposition (restock_sellable, quarantine, write_off_scrap, vendor_return)."),
    )
    inspection_notes = models.TextField(
        _("inspection notes"),
        blank=True,
        default="",
    )
    quantity_returned_now = models.DecimalField(
        _("quantity returned now"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text=_("Quantity returned immediately back to central warehouse."),
    )
    quantity_held_return_later = models.DecimalField(
        _("quantity held for return later"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
        help_text=_("Quantity held at outlet to be returned in a later batch."),
    )
    line_decision = models.CharField(
        _("line decision"),
        max_length=32,
        blank=True,
        default="",
        help_text=_("Decision for this specific line item (e.g. accepted, returned_now, return_later)."),
    )
    notes = models.CharField(
        _("notes"),
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock transfer line")
        verbose_name_plural = _("stock transfer lines")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product.name}"


class StockAdjustment(TenantModel):
    """Document recording quantity/value corrections and shrinkage."""

    adjustment_number = models.CharField(_("adjustment number"), max_length=64)
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="adjustments",
        verbose_name=_("warehouse"),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_adjustments",
        verbose_name=_("branch outlet"),
    )
    location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="adjustments",
        verbose_name=_("inventory location"),
    )
    reason = models.CharField(
        _("reason"),
        max_length=32,
        choices=AdjustmentReason.choices,
        default=AdjustmentReason.COUNT_VARIANCE,
    )
    status = models.CharField(
        _("status"),
        max_length=32,
        default="draft",
    )
    notes = models.TextField(_("notes"), blank=True, default="")
    confirmed_at = models.DateTimeField(_("confirmed at"), null=True, blank=True)
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_stock_adjustments",
        verbose_name=_("approved by"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock adjustment")
        verbose_name_plural = _("stock adjustments")
        ordering = ["-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "adjustment_number"],
                name="uniq_adjustment_org_number",
            ),
        ]

    def __str__(self) -> str:
        facility = self.warehouse.name if self.warehouse else (self.branch.name if self.branch else "")
        return f"{self.adjustment_number} ({self.get_reason_display()}) @ {facility}"


class StockAdjustmentLine(TenantModel):
    """Line item in a stock adjustment."""

    adjustment = models.ForeignKey(
        StockAdjustment,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("adjustment"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("product variant"),
    )
    quantity = models.DecimalField(
        _("quantity delta"),
        max_digits=18,
        decimal_places=4,
    )
    unit_cost = models.DecimalField(
        _("unit cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock adjustment line")
        verbose_name_plural = _("stock adjustment lines")
        ordering = ["id"]

    def __str__(self) -> str:
        sign = "+" if self.quantity > Decimal("0") else ""
        return f"{sign}{self.quantity} x {self.product.name}"


class StockCount(TenantModel):
    """Cycle count or periodic physical inventory audit."""

    count_number = models.CharField(_("count number"), max_length=64)
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="stock_counts",
        verbose_name=_("warehouse"),
    )
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=CountStatus.choices,
        default=CountStatus.DRAFT,
    )
    scheduled_date = models.DateField(
        _("scheduled date"),
        default=timezone.now,
    )
    notes = models.TextField(_("notes"), blank=True, default="")
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    adjustment = models.ForeignKey(
        "inventory.StockAdjustment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_counts",
        verbose_name=_("reconciliation adjustment"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock count")
        verbose_name_plural = _("stock counts")
        ordering = ["-scheduled_date", "-created_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "count_number"],
                name="uniq_count_org_number",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.count_number} ({self.get_status_display()}) @ {self.warehouse.name}"


class StockCountLine(TenantModel):
    """Line item in a stock count recording expected vs counted inventory."""

    count = models.ForeignKey(
        StockCount,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("count"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("product variant"),
    )
    expected_qty = models.DecimalField(
        _("expected quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    counted_qty = models.DecimalField(
        _("counted quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    variance = models.DecimalField(
        _("variance quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock count line")
        verbose_name_plural = _("stock count lines")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.product.name}: expected {self.expected_qty}, counted {self.counted_qty}"


class Batch(TenantModel):
    """Product batch / lot with manufacturing and expiration dates."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="batches",
        verbose_name=_("product"),
    )
    batch_number = models.CharField(_("batch / lot number"), max_length=64)
    manufacturing_date = models.DateField(_("manufacturing date"), null=True, blank=True)
    expiry_date = models.DateField(_("expiry date"), null=True, blank=True)
    received_date = models.DateField(_("received date"), default=timezone.now)
    notes = models.TextField(_("notes"), blank=True, default="")
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("batch")
        verbose_name_plural = _("batches")
        ordering = ["expiry_date", "batch_number"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "product", "batch_number"],
                name="uniq_batch_org_product_number",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "product", "expiry_date"]),
            models.Index(fields=["organization", "batch_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} (Batch: {self.batch_number})"

    @property
    def is_expired(self) -> bool:
        if self.expiry_date:
            return self.expiry_date < timezone.now().date()
        return False

    @property
    def days_until_expiry(self) -> int | None:
        if self.expiry_date:
            return (self.expiry_date - timezone.now().date()).days
        return None


class BatchStock(TenantModel):
    """Tracks current stock of a specific batch in a warehouse."""

    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="stock_levels",
        verbose_name=_("batch"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.CASCADE,
        related_name="batch_stocks",
        verbose_name=_("warehouse"),
    )
    quantity = models.DecimalField(
        _("quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("batch stock")
        verbose_name_plural = _("batch stocks")
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "batch", "warehouse"],
                name="uniq_batchstock_org_batch_wh",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "warehouse", "quantity"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch.batch_number} @ {self.warehouse.name}: {self.quantity}"


class SerialStatus(models.TextChoices):
    IN_STOCK = "in_stock", _("In Stock")
    ISSUED = "issued", _("Issued")
    IN_TRANSIT = "in_transit", _("In Transit")
    RETURNED = "returned", _("Returned")
    DAMAGED = "damaged", _("Damaged")


class SerialNumber(TenantModel):
    """Individual serialized item tracked through its inventory lifecycle."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="serial_numbers",
        verbose_name=_("product"),
    )
    serial_number = models.CharField(_("serial number"), max_length=128)
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="serial_numbers",
        verbose_name=_("warehouse"),
    )
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=SerialStatus.choices,
        default=SerialStatus.IN_STOCK,
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="serial_numbers",
        verbose_name=_("batch"),
    )
    last_movement = models.ForeignKey(
        "inventory.StockMovement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="serial_numbers",
        verbose_name=_("last movement"),
    )
    notes = models.TextField(_("notes"), blank=True, default="")

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("serial number")
        verbose_name_plural = _("serial numbers")
        ordering = ["serial_number"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "product", "serial_number"],
                name="uniq_serial_org_product_number",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "product", "status"]),
            models.Index(fields=["organization", "warehouse", "status"]),
            models.Index(fields=["organization", "serial_number"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} [SN: {self.serial_number}] ({self.get_status_display()})"


class StockCostLayer(TenantModel):
    """Individual intake cost layer for First-In, First-Out (FIFO) inventory costing."""

    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="cost_layers",
        verbose_name=_("product"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cost_layers",
        verbose_name=_("product variant"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.CASCADE,
        related_name="cost_layers",
        verbose_name=_("warehouse"),
    )
    unit_cost = models.DecimalField(
        _("unit cost"),
        max_digits=18,
        decimal_places=4,
    )
    initial_quantity = models.DecimalField(
        _("initial quantity"),
        max_digits=18,
        decimal_places=4,
    )
    remaining_quantity = models.DecimalField(
        _("remaining quantity"),
        max_digits=18,
        decimal_places=4,
    )
    received_at = models.DateTimeField(
        _("received at"),
        default=timezone.now,
    )
    movement = models.ForeignKey(
        "inventory.StockMovement",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cost_layers",
        verbose_name=_("source movement"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock cost layer")
        verbose_name_plural = _("stock cost layers")
        ordering = ["received_at", "id"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "warehouse", "product", "remaining_quantity"]),
            models.Index(fields=["organization", "received_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.product.name} @ {self.warehouse.name}: {self.remaining_quantity}/"
            f"{self.initial_quantity} @ ${self.unit_cost}"
        )


class DiscrepancyType(models.TextChoices):
    LEDGER_BALANCE_MISMATCH = "ledger_balance_mismatch", _("Ledger vs Balance Mismatch")
    PHYSICAL_COUNT_VARIANCE = "physical_count_variance", _("Physical Count Variance")
    UNRECEIVED_TRANSFER = "unreceived_transfer", _("Unreceived or Overdue Transfer")
    NEGATIVE_INVENTORY = "negative_inventory", _("Negative Inventory Anomaly")
    DUPLICATE_MOVEMENT = "duplicate_movement", _("Suspected Duplicate Movement")
    MISSING_REFERENCE = "missing_reference", _("Missing Transaction Reference")


class ReconciliationIncidentStatus(models.TextChoices):
    OPEN = "open", _("Open")
    INVESTIGATING = "investigating", _("Under Investigation")
    RESOLVED = "resolved", _("Resolved")
    DISMISSED = "dismissed", _("Dismissed")


class InventoryReconciliationIncident(TenantModel):
    """Tracks audit and integrity discrepancies detected in inventory for auditable resolution."""

    incident_number = models.CharField(_("incident number"), max_length=64)
    location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reconciliation_incidents",
        verbose_name=_("location"),
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reconciliation_incidents",
        verbose_name=_("warehouse"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reconciliation_incidents",
        verbose_name=_("product"),
    )
    discrepancy_type = models.CharField(
        _("discrepancy type"),
        max_length=32,
        choices=DiscrepancyType.choices,
    )
    severity = models.CharField(_("severity"), max_length=16, default="medium")
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=ReconciliationIncidentStatus.choices,
        default=ReconciliationIncidentStatus.OPEN,
    )
    expected_quantity = models.DecimalField(
        _("expected quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    actual_quantity = models.DecimalField(
        _("actual quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    variance = models.DecimalField(
        _("variance"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    description = models.TextField(_("description"), blank=True, default="")
    resolution_notes = models.TextField(_("resolution notes"), blank=True, default="")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_reconciliation_incidents",
        verbose_name=_("resolved by"),
    )
    resolved_at = models.DateTimeField(_("resolved at"), null=True, blank=True)
    adjustment = models.ForeignKey(
        StockAdjustment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_incidents",
        verbose_name=_("resolution adjustment"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("inventory reconciliation incident")
        verbose_name_plural = _("inventory reconciliation incidents")
        ordering = ["-created_at"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "status", "-created_at"]),
            models.Index(fields=["organization", "discrepancy_type"]),
            models.Index(fields=["organization", "location", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.incident_number}: {self.get_discrepancy_type_display()} ({self.get_status_display()})"


# Canonical aliases for ERP domain clarity
InventoryBalance = StockLevel
InventoryLedger = StockMovement


class StockIntake(TenantModel):
    """Document recording physical stocking of products and ingredients into warehouse storage."""

    class IntakeType(models.TextChoices):
        PURCHASE_RECEIPT = "purchase_receipt", _("Purchase Order Receipt")
        SUPPLIER_DELIVERY = "supplier_delivery", _("Supplier Delivery")
        PRODUCTION_BATCH = "production_batch", _("Production / Kitchen Batch")
        OPENING_BALANCE = "opening_balance", _("Opening Stock Balance")
        VENDOR_INTAKE = "vendor_intake", _("Vendor Consignment")
        DIRECT_STOCKING = "direct_stocking", _("Direct Warehouse Stocking")

    intake_number = models.CharField(_("intake number"), max_length=64, db_index=True)
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.PROTECT,
        related_name="stock_intakes",
        verbose_name=_("warehouse"),
    )
    storage_type = models.ForeignKey(
        "inventory.WarehouseStorageType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_intakes",
        verbose_name=_("storage compartment"),
    )
    location = models.ForeignKey(
        "inventory.InventoryLocation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_intakes",
        verbose_name=_("location / bin"),
    )
    intake_type = models.CharField(
        _("intake type"),
        max_length=64,
        choices=IntakeType.choices,
        default=IntakeType.DIRECT_STOCKING,
    )
    reference_number = models.CharField(
        _("external reference / bill #"),
        max_length=128,
        blank=True,
        default="",
    )
    supplier_name = models.CharField(
        _("supplier / source"),
        max_length=255,
        blank=True,
        default="",
    )
    date = models.DateField(
        _("stocking date"),
        default=timezone.now,
    )
    total_quantity = models.DecimalField(
        _("total quantity"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cost = models.DecimalField(
        _("total cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    notes = models.TextField(_("notes"), blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_intakes",
        verbose_name=_("created by"),
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock intake")
        verbose_name_plural = _("stock intakes")
        ordering = ["-date", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["organization", "intake_number"],
                name="uniq_stock_intake_number_per_org",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["organization", "warehouse", "-date"]),
            models.Index(fields=["organization", "-date"]),
        ]

    def __str__(self) -> str:
        return f"{self.intake_number} - {self.warehouse.name} ({self.total_quantity} items)"


class StockIntakeLine(TenantModel):
    """Line item for a warehouse stock intake session."""

    intake = models.ForeignKey(
        StockIntake,
        on_delete=models.CASCADE,
        related_name="lines",
        verbose_name=_("stock intake"),
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="intake_lines",
        verbose_name=_("product / ingredient"),
    )
    variant = models.ForeignKey(
        "catalog.ProductVariant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intake_lines",
        verbose_name=_("variant"),
    )
    quantity = models.DecimalField(
        _("quantity"),
        max_digits=18,
        decimal_places=4,
    )
    unit_cost = models.DecimalField(
        _("unit cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cost = models.DecimalField(
        _("total cost"),
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    batch_number = models.CharField(
        _("batch / lot number"),
        max_length=64,
        blank=True,
        default="",
    )
    expiry_date = models.DateField(
        _("expiry date"),
        null=True,
        blank=True,
    )
    notes = models.CharField(
        _("line notes"),
        max_length=255,
        blank=True,
        default="",
    )

    class Meta:
        base_manager_name = "all_tenants"
        verbose_name = _("stock intake line")
        verbose_name_plural = _("stock intake lines")
        ordering = ["id"]

    def __str__(self) -> str:
        return f"{self.product.name} ({self.quantity}) @ {self.unit_cost}"

