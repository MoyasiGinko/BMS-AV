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


class AdjustmentReason(models.TextChoices):
    DAMAGE = "damage", _("Damaged Goods")
    SPOILAGE = "spoilage", _("Spoilage / Expiry")
    SHRINKAGE = "shrinkage", _("Shrinkage / Theft")
    COUNT_VARIANCE = "count_variance", _("Cycle Count Variance")
    CORRECTION = "correction", _("Correction / Other")


class TransferStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    IN_TRANSIT = "in_transit", _("In Transit")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


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
            models.Index(fields=["organization", "on_hand"]),
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
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=TransferStatus.choices,
        default=TransferStatus.DRAFT,
    )
    notes = models.TextField(_("notes"), blank=True, default="")
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
        ]

    def __str__(self) -> str:
        return f"{self.transfer_number}: {self.source_warehouse.name} -> {self.destination_warehouse.name}"

    @property
    def is_in_transit(self) -> bool:
        return self.status == TransferStatus.IN_TRANSIT


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
        related_name="adjustments",
        verbose_name=_("warehouse"),
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
        return f"{self.adjustment_number} ({self.get_reason_display()}) @ {self.warehouse.name}"


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
