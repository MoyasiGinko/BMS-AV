"""Admin configuration for the Sales and Invoicing module."""

from django.contrib import admin

from apps.sales.models import (
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
    PaymentRefund,
    PaymentReminderLog,
    PaymentReminderRule,
    Quote,
    QuoteLine,
    RecurringInvoiceLine,
    RecurringInvoiceProfile,
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


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    readonly_fields = ("invoice", "amount", "created_at")


class PaymentRefundInline(admin.TabularInline):
    model = PaymentRefund
    extra = 0
    readonly_fields = ("refund_number", "amount", "refund_date", "reason", "journal_entry")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "payment_number",
        "customer",
        "payment_date",
        "payment_method",
        "amount",
        "allocated_amount",
        "unallocated_amount",
        "status",
        "organization",
    )
    list_filter = ("status", "payment_method", "organization")
    search_fields = ("payment_number", "customer__name", "reference")
    readonly_fields = (
        "public_id",
        "allocated_amount",
        "unallocated_amount",
        "refunded_amount",
        "journal_entry",
        "created_at",
        "updated_at",
    )
    inlines = [PaymentAllocationInline, PaymentRefundInline]


class RecurringInvoiceLineInline(admin.TabularInline):
    model = RecurringInvoiceLine
    extra = 0


@admin.register(RecurringInvoiceProfile)
class RecurringInvoiceProfileAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "customer",
        "frequency",
        "next_issue_date",
        "status",
        "cycles_completed",
        "auto_post",
        "organization",
    )
    list_filter = ("status", "frequency", "auto_post", "organization")
    search_fields = ("title", "customer__name")
    readonly_fields = ("public_id", "cycles_completed", "last_issue_date", "created_at", "updated_at")
    inlines = [RecurringInvoiceLineInline]


@admin.register(PaymentReminderRule)
class PaymentReminderRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "timing_days", "is_active", "subject_template")
    list_filter = ("is_active", "organization")
    search_fields = ("name", "subject_template")
    readonly_fields = ("public_id", "created_at", "updated_at")


@admin.register(PaymentReminderLog)
class PaymentReminderLogAdmin(admin.ModelAdmin):
    list_display = (
        "invoice",
        "timing_days",
        "recipient_email",
        "status",
        "sent_at",
        "organization",
    )
    list_filter = ("status", "organization")
    search_fields = ("invoice__invoice_number", "recipient_email")
    readonly_fields = ("public_id", "sent_at", "created_at")
