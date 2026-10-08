"""Django admin registration for inventory models."""

from __future__ import annotations

from django.contrib import admin

from apps.inventory.models import (
    StockAdjustment,
    StockAdjustmentLine,
    StockCount,
    StockCountLine,
    StockLevel,
    StockMovement,
    StockReservation,
    StockTransfer,
    StockTransferLine,
)


@admin.register(StockLevel)
class StockLevelAdmin(admin.ModelAdmin):
    list_display = ("product", "variant", "warehouse", "on_hand", "reserved", "avg_cost", "organization")
    list_filter = ("warehouse",)
    search_fields = ("product__name", "product__sku", "warehouse__name")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "type",
        "product",
        "warehouse",
        "quantity",
        "unit_cost",
        "total_cost",
        "organization",
    )
    list_filter = ("type", "warehouse")
    search_fields = ("product__name", "product__sku", "reference_type", "reference_id")
    readonly_fields = [f.name for f in StockMovement._meta.fields]


class StockTransferLineInline(admin.TabularInline):
    model = StockTransferLine
    extra = 0


@admin.register(StockTransfer)
class StockTransferAdmin(admin.ModelAdmin):
    list_display = (
        "transfer_number",
        "source_warehouse",
        "destination_warehouse",
        "status",
        "created_at",
        "organization",
    )
    list_filter = ("status",)
    search_fields = ("transfer_number",)
    inlines = [StockTransferLineInline]


class StockAdjustmentLineInline(admin.TabularInline):
    model = StockAdjustmentLine
    extra = 0


@admin.register(StockAdjustment)
class StockAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("adjustment_number", "warehouse", "reason", "status", "confirmed_at", "organization")
    list_filter = ("reason", "warehouse")
    search_fields = ("adjustment_number",)
    inlines = [StockAdjustmentLineInline]


class StockCountLineInline(admin.TabularInline):
    model = StockCountLine
    extra = 0


@admin.register(StockCount)
class StockCountAdmin(admin.ModelAdmin):
    list_display = ("count_number", "warehouse", "status", "scheduled_date", "organization")
    list_filter = ("status", "warehouse")
    search_fields = ("count_number",)
    inlines = [StockCountLineInline]


@admin.register(StockReservation)
class StockReservationAdmin(admin.ModelAdmin):
    list_display = ("product", "warehouse", "quantity", "status", "expires_at", "organization")
    list_filter = ("status", "warehouse")
    search_fields = ("product__name", "reference_id")
