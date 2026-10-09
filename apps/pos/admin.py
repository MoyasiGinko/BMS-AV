"""Django admin configuration for the Point of Sale (POS) module."""

from django.contrib import admin

from apps.pos.models import POSHeldCart, POSRegister, POSSale, POSShift


@admin.register(POSRegister)
class POSRegisterAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "branch", "warehouse", "is_active", "organization")
    list_filter = ("is_active", "organization")
    search_fields = ("code", "name", "branch__name", "warehouse__name")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(POSShift)
class POSShiftAdmin(admin.ModelAdmin):
    list_display = (
        "shift_number",
        "register",
        "cashier",
        "status",
        "opening_cash",
        "closing_cash_counted",
        "cash_variance",
        "total_sales_amount",
        "opened_at",
        "closed_at",
        "organization",
    )
    list_filter = ("status", "organization")
    search_fields = ("shift_number", "register__code", "cashier__email")
    readonly_fields = (
        "public_id",
        "shift_number",
        "opened_at",
        "closed_at",
        "expected_cash",
        "cash_variance",
        "total_sales_amount",
        "total_cash_sales",
        "total_card_sales",
        "total_other_sales",
        "variance_journal_entry",
        "created_at",
        "updated_at",
    )


@admin.register(POSSale)
class POSSaleAdmin(admin.ModelAdmin):
    list_display = (
        "receipt_number",
        "register",
        "shift",
        "invoice",
        "customer",
        "total_amount",
        "created_at",
        "organization",
    )
    list_filter = ("organization",)
    search_fields = (
        "receipt_number",
        "register__code",
        "shift__shift_number",
        "invoice__invoice_number",
        "customer__name",
    )
    readonly_fields = (
        "public_id",
        "receipt_number",
        "created_at",
        "updated_at",
    )


@admin.register(POSHeldCart)
class POSHeldCartAdmin(admin.ModelAdmin):
    list_display = ("cart_label", "shift", "total_amount", "created_at", "organization")
    list_filter = ("organization",)
    search_fields = ("cart_label", "shift__shift_number")
    readonly_fields = ("public_id", "created_at", "updated_at")
