"""Admin configuration for the Sales and Invoicing module."""

from django.contrib import admin

from apps.sales.models import (
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    Quote,
    QuoteLine,
    SalesOrder,
    SalesOrderLine,
)


class QuoteLineInline(admin.TabularInline):
    model = QuoteLine
    extra = 0
    readonly_fields = ("line_total", "tax_amount", "discount_amount")


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("quote_number", "customer", "date", "status", "grand_total", "organization")
    list_filter = ("status", "organization")
    search_fields = ("quote_number", "customer__name")
    readonly_fields = ("subtotal", "discount_total", "tax_total", "grand_total", "public_id")
    inlines = [QuoteLineInline]


class SalesOrderLineInline(admin.TabularInline):
    model = SalesOrderLine
    extra = 0
    readonly_fields = ("line_total", "tax_amount", "discount_amount")


@admin.register(SalesOrder)
class SalesOrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "customer", "order_date", "status", "grand_total", "organization")
    list_filter = ("status", "organization")
    search_fields = ("order_number", "customer__name")
    readonly_fields = ("subtotal", "discount_total", "tax_total", "grand_total", "public_id")
    inlines = [SalesOrderLineInline]


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    readonly_fields = ("line_total", "tax_amount", "discount_amount", "unit_cost")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "customer",
        "invoice_date",
        "due_date",
        "status",
        "grand_total",
        "balance_due",
        "organization",
    )
    list_filter = ("status", "organization")
    search_fields = ("invoice_number", "customer__name")
    readonly_fields = (
        "subtotal",
        "discount_total",
        "tax_total",
        "grand_total",
        "balance_due",
        "public_id",
        "journal_entry",
    )
    inlines = [InvoiceLineInline]


class CreditNoteLineInline(admin.TabularInline):
    model = CreditNoteLine
    extra = 0
    readonly_fields = ("line_total", "tax_amount", "unit_cost")


@admin.register(CreditNote)
class CreditNoteAdmin(admin.ModelAdmin):
    list_display = (
        "credit_note_number",
        "customer",
        "credit_note_date",
        "status",
        "grand_total",
        "organization",
    )
    list_filter = ("status", "organization")
    search_fields = ("credit_note_number", "customer__name")
    readonly_fields = ("subtotal", "tax_total", "grand_total", "public_id", "journal_entry")
    inlines = [CreditNoteLineInline]
