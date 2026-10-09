"""High-performance read-only selectors for dashboard widgets and business KPI aggregations."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.core.models import OutboxEvent
from apps.inventory.models import StockLevel
from apps.pos.models import POSSale
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Organization

ZERO_DECIMAL = Decimal("0.0000")


def get_sales_today_kpi(
    organization: Organization,
    *,
    today: datetime.date | None = None,
) -> dict[str, Any]:
    """Calculate today's gross sales, transaction counts, POS vs invoice breakdown, and AOV.

    Reconciles with posted sales invoices and POS sale records.
    """
    target_date = today or timezone.localdate()

    # 1. Posted sales invoices for today
    invoices_qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
        invoice_date=target_date,
    )
    inv_agg = invoices_qs.aggregate(
        total_gross=Sum("grand_total"),
        total_count=Count("id"),
        total_paid=Sum("amount_paid"),
    )
    gross_sales = inv_agg["total_gross"] or ZERO_DECIMAL
    transaction_count = inv_agg["total_count"] or 0
    total_paid = inv_agg["total_paid"] or ZERO_DECIMAL

    # 2. POS sales breakdown for today
    pos_qs = POSSale.all_tenants.filter(
        organization=organization,
        created_at__date=target_date,
    )
    pos_agg = pos_qs.aggregate(
        pos_gross=Sum("grand_total"),
        pos_count=Count("id"),
    )
    pos_gross = pos_agg["pos_gross"] or ZERO_DECIMAL
    pos_count = pos_agg["pos_count"] or 0

    # 3. Direct B2B / Back-office invoices (non-POS)
    direct_count = max(0, transaction_count - pos_count)
    direct_gross = max(ZERO_DECIMAL, gross_sales - pos_gross)

    # 4. Average Order Value (AOV)
    aov = (
        (gross_sales / Decimal(transaction_count)).quantize(Decimal("0.01"))
        if transaction_count > 0
        else Decimal("0.00")
    )

    return {
        "date": target_date,
        "gross_sales": gross_sales,
        "transaction_count": transaction_count,
        "total_paid": total_paid,
        "aov": aov,
        "pos_gross": pos_gross,
        "pos_count": pos_count,
        "direct_gross": direct_gross,
        "direct_count": direct_count,
        "currency": organization.base_currency or "USD",
    }


def get_receivables_kpi(
    organization: Organization,
    *,
    as_of: datetime.date | None = None,
) -> dict[str, Any]:
    """Calculate outstanding customer receivables, overdue balances, aging buckets, and top debtors.

    Reconciles directly with posted open invoices and customer subledgers.
    """
    as_of_date = as_of or timezone.localdate()

    open_invoices_qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
        balance_due__gt=ZERO_DECIMAL,
    )

    total_balance = open_invoices_qs.aggregate(total=Sum("balance_due"))["total"] or ZERO_DECIMAL
    open_count = open_invoices_qs.count()

    overdue_qs = open_invoices_qs.filter(due_date__lt=as_of_date)
    overdue_balance = overdue_qs.aggregate(total=Sum("balance_due"))["total"] or ZERO_DECIMAL
    overdue_count = overdue_qs.count()

    # Aging buckets
    current_balance = (
        open_invoices_qs.filter(Q(due_date__gte=as_of_date) | Q(due_date__isnull=True)).aggregate(
            total=Sum("balance_due")
        )["total"]
        or ZERO_DECIMAL
    )

    days_30_ago = as_of_date - datetime.timedelta(days=30)
    days_60_ago = as_of_date - datetime.timedelta(days=60)

    aging_1_30 = (
        open_invoices_qs.filter(
            due_date__lt=as_of_date,
            due_date__gte=days_30_ago,
        ).aggregate(total=Sum("balance_due"))["total"]
        or ZERO_DECIMAL
    )

    aging_31_60 = (
        open_invoices_qs.filter(
            due_date__lt=days_30_ago,
            due_date__gte=days_60_ago,
        ).aggregate(total=Sum("balance_due"))["total"]
        or ZERO_DECIMAL
    )

    aging_over_60 = (
        open_invoices_qs.filter(
            due_date__lt=days_60_ago,
        ).aggregate(total=Sum("balance_due"))["total"]
        or ZERO_DECIMAL
    )

    # Top debtors
    top_debtors = (
        open_invoices_qs.values("customer__id", "customer__name", "customer__code")
        .annotate(total_due=Sum("balance_due"), invoice_count=Count("id"))
        .order_by("-total_due")[:3]
    )

    return {
        "as_of": as_of_date,
        "total_balance_due": total_balance,
        "open_count": open_count,
        "overdue_balance": overdue_balance,
        "overdue_count": overdue_count,
        "current_balance": current_balance,
        "aging_1_30": aging_1_30,
        "aging_31_60": aging_31_60,
        "aging_over_60": aging_over_60,
        "top_debtors": list(top_debtors),
        "currency": organization.base_currency or "USD",
    }


def get_low_stock_alerts(
    organization: Organization,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Retrieve stock levels that have breached their reorder point or safety stock threshold."""
    breach_qs = (
        StockLevel.all_tenants.filter(organization=organization)
        .select_related("product", "product__unit", "warehouse")
        .filter(
            Q(reorder_point__isnull=False, on_hand__lte=F("reorder_point") + F("reserved"))
            | Q(
                reorder_point__isnull=True,
                product__reorder_level__isnull=False,
                product__reorder_level__gt=0,
                on_hand__lte=F("product__reorder_level") + F("reserved"),
            )
        )
        .order_by("on_hand", "product__name")
    )

    breach_count = breach_qs.count()
    items: list[dict[str, Any]] = []

    for sl in breach_qs[:limit]:
        reorder_pt = sl.reorder_point if sl.reorder_point is not None else sl.product.reorder_level
        reorder_qty = sl.reorder_quantity if sl.reorder_quantity is not None else sl.product.reorder_quantity
        unit_code = sl.product.unit.code if sl.product.unit else "ea"
        items.append(
            {
                "stock_level_id": sl.pk,
                "product_name": sl.product.name,
                "product_sku": sl.product.sku,
                "unit_code": unit_code,
                "warehouse_name": sl.warehouse.name,
                "on_hand": sl.on_hand,
                "available": sl.available,
                "reserved": sl.reserved,
                "reorder_point": reorder_pt,
                "reorder_quantity": reorder_qty,
                "is_out_of_stock": sl.on_hand <= ZERO_DECIMAL,
            }
        )

    return {
        "breach_count": breach_count,
        "has_low_stock": breach_count > 0,
        "items": items,
    }


def get_top_products_kpi(
    organization: Organization,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Retrieve top-selling products ranked by revenue and quantity from posted sales invoices."""
    top_qs = (
        InvoiceLine.all_tenants.filter(
            organization=organization,
            invoice__status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
        )
        .values("product__id", "product__name", "product__sku")
        .annotate(
            units_sold=Sum("quantity"),
            revenue=Sum("line_total"),
        )
        .order_by("-revenue")[:limit]
    )

    top_list = list(top_qs)
    max_revenue = (
        top_list[0]["revenue"]
        if top_list and top_list[0]["revenue"] and top_list[0]["revenue"] > ZERO_DECIMAL
        else Decimal("1.0000")
    )
    total_revenue_top = sum((item["revenue"] or ZERO_DECIMAL for item in top_list), ZERO_DECIMAL)

    products: list[dict[str, Any]] = []
    for rank, item in enumerate(top_list, start=1):
        rev = item["revenue"] or ZERO_DECIMAL
        pct = int((rev / max_revenue) * 100) if max_revenue > ZERO_DECIMAL else 0
        products.append(
            {
                "rank": rank,
                "product_id": item["product__id"],
                "name": item["product__name"],
                "sku": item["product__sku"],
                "units_sold": item["units_sold"] or ZERO_DECIMAL,
                "revenue": rev,
                "percent_of_max": pct,
            }
        )

    return {
        "products": products,
        "total_revenue_top": total_revenue_top,
        "has_sales": len(products) > 0,
        "currency": organization.base_currency or "USD",
    }


def get_recent_activity_feed(
    organization: Organization,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Retrieve live domain events and outbox activity stream for the workspace."""
    events = OutboxEvent.objects.filter(organization=organization).order_by("-created_at")[:limit]

    activity_items: list[dict[str, Any]] = []
    for ev in events:
        friendly_title, badge_color, icon_name = _humanize_event(ev.event_type)
        summary_text = _format_event_summary(ev.event_type, ev.payload)
        activity_items.append(
            {
                "event_id": str(ev.event_id),
                "event_type": ev.event_type,
                "title": friendly_title,
                "summary": summary_text,
                "badge_color": badge_color,
                "icon": icon_name,
                "status": ev.status,
                "created_at": ev.created_at,
            }
        )

    return {
        "items": activity_items,
        "has_activity": len(activity_items) > 0,
    }


def _humanize_event(event_type: str) -> tuple[str, str, str]:
    """Map event type to user-facing title, badge styling, and icon identifier."""
    mapping = {
        "invoice.confirmed": ("Invoice Confirmed", "emerald", "document-check"),
        "invoice.created": ("Invoice Created", "blue", "document-text"),
        "invoice.voided": ("Invoice Voided", "rose", "no-symbol"),
        "pos.sale_completed": ("POS Counter Sale", "emerald", "calculator"),
        "pos.shift_opened": ("POS Shift Opened", "amber", "clock"),
        "pos.shift_closed": ("POS Shift Closed", "slate", "lock-closed"),
        "payment.created": ("Payment Received", "emerald", "banknotes"),
        "payment.refunded": ("Payment Refunded", "rose", "arrow-uturn-left"),
        "customer.created": ("Customer Added", "blue", "user-plus"),
        "stock.adjusted": ("Stock Adjustment", "indigo", "arrows-right-left"),
        "stock.movement": ("Stock Movement", "indigo", "archive-box"),
    }
    if event_type in mapping:
        return mapping[event_type]

    clean_name = event_type.replace(".", " ").replace("_", " ").title()
    return clean_name, "neutral", "bolt"


def _format_event_summary(event_type: str, payload: dict[str, Any]) -> str:
    """Format a succinct, informative description from event payload parameters."""
    if not isinstance(payload, dict):
        return event_type

    formatters = {
        "invoice.confirmed": lambda p: (
            f"Invoice {p.get('invoice_number', '')} confirmed for {p.get('grand_total', '')}".strip()
            if p.get("invoice_number") and p.get("grand_total")
            else f"Invoice {p.get('invoice_number', '')} confirmed".strip()
        ),
        "pos.sale_completed": lambda p: (
            f"Receipt {p.get('receipt_number', '')} completed for {p.get('grand_total', '')}".strip()
            if p.get("receipt_number") and p.get("grand_total")
            else "POS Sale completed"
        ),
        "pos.shift_opened": lambda p: (
            f"Shift {p.get('shift_number', '')}".strip()
            if p.get("shift_number")
            else "Register shift updated"
        ),
        "pos.shift_closed": lambda p: (
            f"Shift {p.get('shift_number', '')}".strip()
            if p.get("shift_number")
            else "Register shift updated"
        ),
        "payment.created": lambda p: (
            (
                f"Payment {p.get('payment_number') or p.get('reference', '')} "
                f"received ({p.get('amount', '')})"
            ).strip()
            if (p.get("payment_number") or p.get("reference")) and p.get("amount")
            else "Customer payment recorded"
        ),
        "payment.refunded": lambda p: (
            f"Refund of {p.get('refund_amount', p.get('amount', ''))} processed"
            if (p.get("refund_amount") or p.get("amount"))
            else "Customer payment refund"
        ),
        "customer.created": lambda p: (
            f"New account created for {p.get('name', '')}"
            if p.get("name")
            else "New customer account created"
        ),
    }

    formatter = formatters.get(event_type)
    if formatter:
        return formatter(payload)
    return f"Event {event_type} logged"
