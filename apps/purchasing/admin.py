"""Django admin registration for Purchasing models."""

from django.contrib import admin

from apps.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReturn,
    PurchaseReturnLine,
    Supplier,
    SupplierBill,
    SupplierBillLine,
    SupplierPayment,
    SupplierPaymentAllocation,
)


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["order_number", "supplier", "status", "order_date", "grand_total"]
    list_filter = ["status", "order_date"]
    search_fields = ["order_number", "supplier__name"]
    inlines = [PurchaseOrderLineInline]


class GoodsReceiptLineInline(admin.TabularInline):
    model = GoodsReceiptLine
    extra = 0


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ["receipt_number", "supplier", "warehouse", "status", "date", "total_cost"]
    list_filter = ["status", "date"]
    search_fields = ["receipt_number", "supplier__name"]
    inlines = [GoodsReceiptLineInline]


class SupplierBillLineInline(admin.TabularInline):
    model = SupplierBillLine
    extra = 0


@admin.register(SupplierBill)
class SupplierBillAdmin(admin.ModelAdmin):
    list_display = ["bill_number", "supplier", "status", "issue_date", "total_amount", "balance_due"]
    list_filter = ["status", "issue_date"]
    search_fields = ["bill_number", "supplier_reference", "supplier__name"]
    inlines = [SupplierBillLineInline]


class SupplierPaymentAllocationInline(admin.TabularInline):
    model = SupplierPaymentAllocation
    extra = 0


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ["payment_number", "supplier", "amount", "payment_date", "payment_method"]
    list_filter = ["payment_method", "payment_date"]
    search_fields = ["payment_number", "reference", "supplier__name"]
    inlines = [SupplierPaymentAllocationInline]


class PurchaseReturnLineInline(admin.TabularInline):
    model = PurchaseReturnLine
    extra = 0


@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ["return_number", "supplier", "status", "return_date", "total_amount"]
    list_filter = ["status", "return_date"]
    search_fields = ["return_number", "supplier__name"]
    inlines = [PurchaseReturnLineInline]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "contact_person", "email", "current_balance", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code", "email"]
