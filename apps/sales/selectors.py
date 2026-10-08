"""Selectors for the Sales and Invoicing module: read-only optimized queries."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from apps.sales.models import (
    CreditNote,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentStatus,
    Quote,
    QuoteStatus,
    SalesOrder,
    SalesOrderStatus,
)
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")


def list_quotes(
    *,
    organization: Organization,
    status: str | None = None,
    customer_id: int | None = None,
    search: str | None = None,
) -> QuerySet[Quote]:
    """Retrieve filtered quotes for an organization."""
    qs = (
        Quote.all_tenants.filter(organization=organization)
        .select_related("customer", "branch")
        .order_by("-date", "-id")
    )
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if search:
        search = search.strip()
        qs = qs.filter(
            Q(quote_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(customer__code__icontains=search)
        )
    return qs


def get_quote(
    *,
    organization: Organization,
    quote_id: int | None = None,
    public_id: str | None = None,
) -> Quote | None:
    """Get single quotation with preloaded lines."""
    qs = (
        Quote.all_tenants.filter(organization=organization)
        .select_related("customer", "branch")
        .prefetch_related("lines__product", "lines__variant")
    )
    if quote_id:
        return qs.filter(pk=quote_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_orders(
    *,
    organization: Organization,
    status: str | None = None,
    customer_id: int | None = None,
    search: str | None = None,
) -> QuerySet[SalesOrder]:
    """Retrieve filtered sales orders for an organization."""
    qs = (
        SalesOrder.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "warehouse", "quote")
        .order_by("-order_date", "-id")
    )
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if search:
        search = search.strip()
        qs = qs.filter(
            Q(order_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(customer__code__icontains=search)
        )
    return qs


def get_order(
    *,
    organization: Organization,
    order_id: int | None = None,
    public_id: str | None = None,
) -> SalesOrder | None:
    """Get single sales order with preloaded lines."""
    qs = (
        SalesOrder.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "warehouse", "quote")
        .prefetch_related("lines__product", "lines__variant")
    )
    if order_id:
        return qs.filter(pk=order_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_invoices(
    *,
    organization: Organization,
    status: str | None = None,
    customer_id: int | None = None,
    search: str | None = None,
    is_overdue: bool | None = None,
) -> QuerySet[Invoice]:
    """Retrieve filtered sales invoices for an organization."""
    qs = (
        Invoice.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "warehouse", "order", "journal_entry")
        .order_by("-invoice_date", "-id")
    )
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if search:
        search = search.strip()
        qs = qs.filter(
            Q(invoice_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(customer__code__icontains=search)
        )
    if is_overdue:
        today = timezone.now().date()
        qs = qs.filter(
            status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
            due_date__lt=today,
            balance_due__gt=DECIMAL_ZERO,
        )
    return qs


def get_invoice(
    *,
    organization: Organization,
    invoice_id: int | None = None,
    public_id: str | None = None,
) -> Invoice | None:
    """Get single invoice with preloaded lines."""
    qs = (
        Invoice.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "warehouse", "order", "journal_entry")
        .prefetch_related("lines__product", "lines__variant")
    )
    if invoice_id:
        return qs.filter(pk=invoice_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_credit_notes(
    *,
    organization: Organization,
    status: str | None = None,
    customer_id: int | None = None,
    search: str | None = None,
) -> QuerySet[CreditNote]:
    """Retrieve filtered credit notes for an organization."""
    qs = (
        CreditNote.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "warehouse", "invoice", "journal_entry")
        .order_by("-credit_note_date", "-id")
    )
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if search:
        search = search.strip()
        qs = qs.filter(
            Q(credit_note_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(customer__code__icontains=search)
        )
    return qs


def get_credit_note(
    *,
    organization: Organization,
    credit_note_id: int | None = None,
    public_id: str | None = None,
) -> CreditNote | None:
    """Get single credit note with preloaded lines."""
    qs = (
        CreditNote.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "warehouse", "invoice", "journal_entry")
        .prefetch_related("lines__product", "lines__variant")
    )
    if credit_note_id:
        return qs.filter(pk=credit_note_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_sales_summary_metrics(*, organization: Organization) -> dict[str, Any]:
    """Calculate key sales dashboard metrics."""
    today = timezone.now().date()
    month_start = today.replace(day=1)

    # Invoices summary
    inv_agg = Invoice.all_tenants.filter(organization=organization).aggregate(
        total_invoiced=Sum(
            "grand_total",
            filter=Q(status__in=[InvoiceStatus.POSTED, InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID]),
        ),
        total_unpaid=Sum(
            "balance_due", filter=Q(status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID])
        ),
        month_invoiced=Sum(
            "grand_total",
            filter=Q(
                status__in=[InvoiceStatus.POSTED, InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID],
                invoice_date__gte=month_start,
            ),
        ),
        overdue_amount=Sum(
            "balance_due",
            filter=Q(
                status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
                due_date__lt=today,
                balance_due__gt=DECIMAL_ZERO,
            ),
        ),
        overdue_count=Count(
            "id",
            filter=Q(
                status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
                due_date__lt=today,
                balance_due__gt=DECIMAL_ZERO,
            ),
        ),
    )

    orders_count = SalesOrder.all_tenants.filter(
        organization=organization,
        status=SalesOrderStatus.CONFIRMED,
    ).count()

    quotes_count = Quote.all_tenants.filter(
        organization=organization,
        status__in=[QuoteStatus.DRAFT, QuoteStatus.SENT],
    ).count()

    return {
        "total_invoiced": inv_agg["total_invoiced"] or DECIMAL_ZERO,
        "total_unpaid": inv_agg["total_unpaid"] or DECIMAL_ZERO,
        "month_invoiced": inv_agg["month_invoiced"] or DECIMAL_ZERO,
        "overdue_amount": inv_agg["overdue_amount"] or DECIMAL_ZERO,
        "overdue_count": inv_agg["overdue_count"] or 0,
        "open_orders": orders_count,
        "open_quotes": quotes_count,
    }


# ============================================================================
# PAYMENT SELECTORS
# ============================================================================


def list_payments(
    *,
    organization: Organization,
    customer_id: int | None = None,
    payment_method: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> QuerySet[Payment]:
    """Retrieve filtered payments for an organization."""
    qs = (
        Payment.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "journal_entry")
        .prefetch_related("allocations__invoice")
        .order_by("-payment_date", "-id")
    )
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if payment_method:
        qs = qs.filter(payment_method=payment_method)
    if status:
        qs = qs.filter(status=status)
    if search:
        search = search.strip()
        qs = qs.filter(
            Q(payment_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(customer__code__icontains=search)
            | Q(reference__icontains=search)
        )
    return qs


def get_payment(
    *,
    organization: Organization,
    payment_id: int | None = None,
    public_id: str | None = None,
) -> Payment | None:
    """Get single payment with preloaded customer and allocations."""
    qs = (
        Payment.all_tenants.filter(organization=organization)
        .select_related("customer", "branch", "journal_entry")
        .prefetch_related("allocations__invoice", "refunds")
    )
    if payment_id:
        return qs.filter(pk=payment_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_customer_unallocated_payments(
    *,
    organization: Organization,
    customer_id: int,
) -> QuerySet[Payment]:
    """Get customer payments with positive unallocated balance available for allocation."""
    return (
        Payment.all_tenants.filter(
            organization=organization,
            customer_id=customer_id,
            status=PaymentStatus.POSTED,
            unallocated_amount__gt=DECIMAL_ZERO,
        )
        .select_related("customer")
        .order_by("payment_date", "id")
    )


def get_customer_outstanding_invoices(
    *,
    organization: Organization,
    customer_id: int,
) -> QuerySet[Invoice]:
    """Get customer invoices with outstanding balance due."""
    return (
        Invoice.all_tenants.filter(
            organization=organization,
            customer_id=customer_id,
            status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
            balance_due__gt=DECIMAL_ZERO,
        )
        .select_related("customer", "warehouse")
        .order_by("invoice_date", "id")
    )


def get_payment_summary(
    *,
    organization: Organization,
) -> dict[str, Any]:
    """Get high-level payment metrics for organization."""
    agg = Payment.all_tenants.filter(
        organization=organization,
        status=PaymentStatus.POSTED,
    ).aggregate(
        total_collected=Sum("amount"),
        total_allocated=Sum("allocated_amount"),
        total_unallocated=Sum("unallocated_amount"),
        count=Count("id"),
    )
    return {
        "total_collected": agg["total_collected"] or DECIMAL_ZERO,
        "total_allocated": agg["total_allocated"] or DECIMAL_ZERO,
        "total_unallocated": agg["total_unallocated"] or DECIMAL_ZERO,
        "count": agg["count"] or 0,
    }
