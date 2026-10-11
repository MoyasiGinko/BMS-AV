"""High-performance read-only selectors for dashboard widgets and business KPI aggregations."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.accounting.models import (
    Account,
    AccountMapping,
    AccountType,
    BankAccount,
    Expense,
    ExpenseStatus,
    JournalEntry,
    JournalLine,
)
from apps.core.models import OutboxEvent
from apps.customers import selectors as customer_selectors
from apps.customers.models import Customer
from apps.inventory.models import StockLevel, StockMovement
from apps.pos.models import POSSale
from apps.purchasing.models import (
    SupplierBill,
    SupplierBillStatus,
)
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


# ===========================================================================
# Reports v1 Selectors
# ===========================================================================


def get_sales_by_product_report(
    organization: Organization,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    branch_id: int | None = None,
    category_id: int | None = None,
) -> dict[str, Any]:
    """Report: Sales breakdown by product with quantity sold, revenue, tax, and average price."""
    lines_qs = InvoiceLine.all_tenants.filter(
        organization=organization,
        invoice__status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
    )
    if start_date:
        lines_qs = lines_qs.filter(invoice__invoice_date__gte=start_date)
    if end_date:
        lines_qs = lines_qs.filter(invoice__invoice_date__lte=end_date)
    if branch_id:
        lines_qs = lines_qs.filter(
            Q(invoice__branch_id=branch_id) | Q(invoice__warehouse__branch_id=branch_id)
        )
    if category_id:
        lines_qs = lines_qs.filter(product__category_id=category_id)

    aggregated = (
        lines_qs.values(
            "product__id",
            "product__sku",
            "product__name",
            "product__category__name",
            "product__unit__code",
        )
        .annotate(
            quantity_sold=Sum("quantity"),
            gross_sales=Sum("line_total"),
            tax_total=Sum("tax_amount"),
        )
        .order_by("-gross_sales", "product__name")
    )

    rows: list[dict[str, Any]] = []
    total_qty = ZERO_DECIMAL
    total_gross = ZERO_DECIMAL
    total_tax = ZERO_DECIMAL

    for item in aggregated:
        qty = item["quantity_sold"] or ZERO_DECIMAL
        gross = item["gross_sales"] or ZERO_DECIMAL
        tax = item["tax_total"] or ZERO_DECIMAL
        net = gross - tax
        avg_price = (gross / qty).quantize(Decimal("0.0001")) if qty > ZERO_DECIMAL else ZERO_DECIMAL

        total_qty += qty
        total_gross += gross
        total_tax += tax

        rows.append(
            {
                "product_id": item["product__id"],
                "sku": item["product__sku"],
                "name": item["product__name"],
                "category_name": item["product__category__name"] or "Uncategorized",
                "unit_code": item["product__unit__code"] or "ea",
                "quantity_sold": qty,
                "gross_sales": gross,
                "tax_total": tax,
                "net_sales": net,
                "avg_price": avg_price,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "product_count": len(rows),
            "total_quantity": total_qty,
            "total_gross_sales": total_gross,
            "total_tax": total_tax,
            "total_net_sales": total_gross - total_tax,
        },
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
            "category_id": category_id,
        },
    }


def get_sales_by_customer_report(
    organization: Organization,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    branch_id: int | None = None,
    customer_id: int | None = None,
) -> dict[str, Any]:
    """Report: Sales breakdown by customer with total invoiced, paid, and balance due."""
    inv_qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
    )
    if start_date:
        inv_qs = inv_qs.filter(invoice_date__gte=start_date)
    if end_date:
        inv_qs = inv_qs.filter(invoice_date__lte=end_date)
    if branch_id:
        inv_qs = inv_qs.filter(Q(branch_id=branch_id) | Q(warehouse__branch_id=branch_id))
    if customer_id:
        inv_qs = inv_qs.filter(customer_id=customer_id)

    aggregated = (
        inv_qs.values(
            "customer__id",
            "customer__code",
            "customer__name",
            "customer__email",
            "customer__phone",
        )
        .annotate(
            invoice_count=Count("id"),
            gross_sales=Sum("grand_total"),
            tax_total=Sum("tax_total"),
            balance_due=Sum("balance_due"),
        )
        .order_by("-gross_sales", "customer__name")
    )

    rows: list[dict[str, Any]] = []
    tot_invoices = 0
    tot_gross = ZERO_DECIMAL
    tot_tax = ZERO_DECIMAL
    tot_balance = ZERO_DECIMAL
    tot_paid = ZERO_DECIMAL

    for item in aggregated:
        cnt = item["invoice_count"] or 0
        gross = item["gross_sales"] or ZERO_DECIMAL
        tax = item["tax_total"] or ZERO_DECIMAL
        bal = item["balance_due"] or ZERO_DECIMAL
        paid = gross - bal

        tot_invoices += cnt
        tot_gross += gross
        tot_tax += tax
        tot_balance += bal
        tot_paid += paid

        rows.append(
            {
                "customer_id": item["customer__id"],
                "code": item["customer__code"],
                "name": item["customer__name"],
                "email": item["customer__email"] or "",
                "phone": item["customer__phone"] or "",
                "invoice_count": cnt,
                "gross_sales": gross,
                "tax_total": tax,
                "paid_amount": paid,
                "balance_due": bal,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "customer_count": len(rows),
            "total_invoices": tot_invoices,
            "total_gross_sales": tot_gross,
            "total_tax": tot_tax,
            "total_paid": tot_paid,
            "total_balance_due": tot_balance,
        },
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
            "customer_id": customer_id,
        },
    }


def get_sales_by_branch_report(
    organization: Organization,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Report: Sales breakdown by operational branch with POS vs direct breakdown."""
    inv_qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
    )
    if start_date:
        inv_qs = inv_qs.filter(invoice_date__gte=start_date)
    if end_date:
        inv_qs = inv_qs.filter(invoice_date__lte=end_date)

    aggregated = (
        inv_qs.values(
            "warehouse__branch__id",
            "warehouse__branch__code",
            "warehouse__branch__name",
        )
        .annotate(
            invoice_count=Count("id"),
            direct_sales=Sum("grand_total", filter=Q(pos_sales__isnull=True)),
            pos_sales=Sum("grand_total", filter=Q(pos_sales__isnull=False)),
            gross_sales=Sum("grand_total"),
            tax_total=Sum("tax_total"),
            net_sales=Sum("subtotal"),
        )
        .order_by("-gross_sales")
    )

    rows: list[dict[str, Any]] = []
    tot_invoices = 0
    tot_direct = ZERO_DECIMAL
    tot_pos = ZERO_DECIMAL
    tot_gross = ZERO_DECIMAL
    tot_tax = ZERO_DECIMAL
    tot_net = ZERO_DECIMAL

    for item in aggregated:
        cnt = item["invoice_count"] or 0
        direct = item["direct_sales"] or ZERO_DECIMAL
        pos = item["pos_sales"] or ZERO_DECIMAL
        gross = item["gross_sales"] or ZERO_DECIMAL
        tax = item["tax_total"] or ZERO_DECIMAL
        net = item["net_sales"] or (gross - tax)

        tot_invoices += cnt
        tot_direct += direct
        tot_pos += pos
        tot_gross += gross
        tot_tax += tax
        tot_net += net

        branch_name = item["warehouse__branch__name"] or "HQ / Unassigned"
        branch_code = item["warehouse__branch__code"] or "MAIN"

        rows.append(
            {
                "branch_id": item["warehouse__branch__id"],
                "code": branch_code,
                "name": branch_name,
                "invoice_count": cnt,
                "direct_sales": direct,
                "pos_sales": pos,
                "gross_sales": gross,
                "tax_total": tax,
                "net_sales": net,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "branch_count": len(rows),
            "total_invoices": tot_invoices,
            "total_direct_sales": tot_direct,
            "total_pos_sales": tot_pos,
            "total_gross_sales": tot_gross,
            "total_tax": tot_tax,
            "total_net_sales": tot_net,
        },
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
        },
    }


def get_sales_by_day_report(
    organization: Organization,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    branch_id: int | None = None,
) -> dict[str, Any]:
    """Report: Daily sales trends showing order volume, POS vs direct sales, and net revenue."""
    inv_qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
    )
    if start_date:
        inv_qs = inv_qs.filter(invoice_date__gte=start_date)
    if end_date:
        inv_qs = inv_qs.filter(invoice_date__lte=end_date)
    if branch_id:
        inv_qs = inv_qs.filter(Q(branch_id=branch_id) | Q(warehouse__branch_id=branch_id))

    aggregated = (
        inv_qs.values("invoice_date")
        .annotate(
            invoice_count=Count("id"),
            direct_sales=Sum("grand_total", filter=Q(pos_sales__isnull=True)),
            pos_sales=Sum("grand_total", filter=Q(pos_sales__isnull=False)),
            gross_sales=Sum("grand_total"),
            tax_total=Sum("tax_total"),
            net_sales=Sum("subtotal"),
        )
        .order_by("invoice_date")
    )

    rows: list[dict[str, Any]] = []
    tot_invoices = 0
    tot_direct = ZERO_DECIMAL
    tot_pos = ZERO_DECIMAL
    tot_gross = ZERO_DECIMAL
    tot_tax = ZERO_DECIMAL
    tot_net = ZERO_DECIMAL

    for item in aggregated:
        cnt = item["invoice_count"] or 0
        direct = item["direct_sales"] or ZERO_DECIMAL
        pos = item["pos_sales"] or ZERO_DECIMAL
        gross = item["gross_sales"] or ZERO_DECIMAL
        tax = item["tax_total"] or ZERO_DECIMAL
        net = item["net_sales"] or (gross - tax)

        tot_invoices += cnt
        tot_direct += direct
        tot_pos += pos
        tot_gross += gross
        tot_tax += tax
        tot_net += net

        rows.append(
            {
                "date": item["invoice_date"],
                "invoice_count": cnt,
                "direct_sales": direct,
                "pos_sales": pos,
                "gross_sales": gross,
                "tax_total": tax,
                "net_sales": net,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "days_count": len(rows),
            "total_invoices": tot_invoices,
            "total_direct_sales": tot_direct,
            "total_pos_sales": tot_pos,
            "total_gross_sales": tot_gross,
            "total_tax": tot_tax,
            "total_net_sales": tot_net,
        },
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "branch_id": branch_id,
        },
    }


def get_stock_valuation_report(
    organization: Organization,
    *,
    warehouse_id: int | None = None,
    category_id: int | None = None,
    low_stock_only: bool = False,
) -> dict[str, Any]:
    """Report: Inventory stock valuation with on-hand, reserved, unit cost, and total value."""
    stock_qs = (
        StockLevel.all_tenants.filter(organization=organization)
        .select_related("product", "product__category", "product__unit", "warehouse")
        .order_by("warehouse__name", "product__name")
    )
    if warehouse_id:
        stock_qs = stock_qs.filter(warehouse_id=warehouse_id)
    if category_id:
        stock_qs = stock_qs.filter(product__category_id=category_id)

    rows: list[dict[str, Any]] = []
    tot_on_hand = ZERO_DECIMAL
    tot_reserved = ZERO_DECIMAL
    tot_available = ZERO_DECIMAL
    tot_valuation = ZERO_DECIMAL
    low_stock_count = 0

    for level in stock_qs:
        prod = level.product
        reorder_point = prod.reorder_level or ZERO_DECIMAL
        is_low = level.on_hand <= reorder_point

        if low_stock_only and not is_low:
            continue

        unit_cost = prod.cost_price or ZERO_DECIMAL
        val = (level.on_hand * unit_cost).quantize(Decimal("0.0001"))
        avail = level.on_hand - level.reserved

        tot_on_hand += level.on_hand
        tot_reserved += level.reserved
        tot_available += avail
        tot_valuation += val
        if is_low:
            low_stock_count += 1

        rows.append(
            {
                "product_id": prod.pk,
                "sku": prod.sku,
                "name": prod.name,
                "category_name": prod.category.name if prod.category else "Uncategorized",
                "unit_code": prod.unit.code if prod.unit else "ea",
                "warehouse_id": level.warehouse.pk,
                "warehouse_name": level.warehouse.name,
                "on_hand": level.on_hand,
                "reserved": level.reserved,
                "available": avail,
                "unit_cost": unit_cost,
                "valuation": val,
                "reorder_level": reorder_point,
                "is_low_stock": is_low,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "item_count": len(rows),
            "total_on_hand": tot_on_hand,
            "total_reserved": tot_reserved,
            "total_available": tot_available,
            "total_valuation": tot_valuation,
            "low_stock_count": low_stock_count,
        },
        "filters": {
            "warehouse_id": warehouse_id,
            "category_id": category_id,
            "low_stock_only": low_stock_only,
        },
    }


def get_stock_movement_report(
    organization: Organization,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    movement_type: str | None = None,
) -> dict[str, Any]:
    """Report: Complete inventory ledger / stock movement audit log."""
    mov_qs = (
        StockMovement.all_tenants.filter(organization=organization)
        .select_related("product", "product__unit", "warehouse", "created_by")
        .order_by("-occurred_at", "-id")
    )
    if start_date:
        mov_qs = mov_qs.filter(occurred_at__date__gte=start_date)
    if end_date:
        mov_qs = mov_qs.filter(occurred_at__date__lte=end_date)
    if product_id:
        mov_qs = mov_qs.filter(product_id=product_id)
    if warehouse_id:
        mov_qs = mov_qs.filter(warehouse_id=warehouse_id)
    if movement_type:
        mov_qs = mov_qs.filter(type=movement_type)

    rows: list[dict[str, Any]] = []
    tot_inflow_qty = ZERO_DECIMAL
    tot_outflow_qty = ZERO_DECIMAL
    net_qty = ZERO_DECIMAL
    tot_inflow_cost = ZERO_DECIMAL
    tot_outflow_cost = ZERO_DECIMAL

    for m in mov_qs:
        qty = m.quantity
        cost = m.total_cost or (abs(qty) * m.unit_cost)

        if qty >= ZERO_DECIMAL:
            tot_inflow_qty += qty
            tot_inflow_cost += cost
        else:
            tot_outflow_qty += abs(qty)
            tot_outflow_cost += cost
        net_qty += qty

        actor = m.created_by.email if m.created_by else "System"
        ref = m.reference_id or m.reference_type or "Direct"

        rows.append(
            {
                "id": m.pk,
                "occurred_at": m.occurred_at,
                "movement_type": m.type,
                "movement_type_display": m.get_type_display(),
                "reference_type": m.reference_type,
                "reference_id": ref,
                "warehouse_name": m.warehouse.name,
                "product_sku": m.product.sku,
                "product_name": m.product.name,
                "unit_code": m.product.unit.code if m.product.unit else "ea",
                "quantity": qty,
                "unit_cost": m.unit_cost,
                "total_cost": cost,
                "actor_name": actor,
                "notes": m.notes,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "movement_count": len(rows),
            "total_inflow_qty": tot_inflow_qty,
            "total_outflow_qty": tot_outflow_qty,
            "net_qty": net_qty,
            "total_inflow_cost": tot_inflow_cost,
            "total_outflow_cost": tot_outflow_cost,
        },
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "movement_type": movement_type,
        },
    }


def get_customer_statement_report(
    organization: Organization,
    *,
    customer_id: int,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    """Report: Customer statement with opening balance, ledger rows, closing balance, and aging."""
    customer = Customer.all_tenants.filter(organization=organization, pk=customer_id).first()
    if not customer:
        raise ValueError(f"Customer with ID {customer_id} does not exist in this organization.")

    stmt = customer_selectors.get_customer_statement(
        organization=organization,
        customer=customer,
        start_date=start_date,
        end_date=end_date,
    )

    lines: list[dict[str, Any]] = []
    for line_dict in stmt["lines"]:
        entry = line_dict["entry"]
        lines.append(
            {
                "occurred_at": entry.occurred_at,
                "entry_type": entry.entry_type,
                "entry_type_display": entry.get_entry_type_display(),
                "reference_number": entry.reference_number or entry.reference_id or "-",
                "description": entry.description or entry.get_entry_type_display(),
                "debit": entry.debit,
                "credit": entry.credit,
                "running_balance": line_dict["running_balance"],
            }
        )

    return {
        "customer": {
            "id": customer.pk,
            "code": customer.code,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "tax_id": customer.tax_id,
            "current_balance": customer.current_balance,
            "credit_limit": customer.credit_limit,
        },
        "period": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "opening_balance": stmt["opening_balance"],
        "lines": lines,
        "closing_balance": stmt["closing_balance"],
        "summary": {
            "total_debits": stmt["total_debits"],
            "total_credits": stmt["total_credits"],
            "net_change": stmt["total_debits"] - stmt["total_credits"],
        },
        "aging": stmt["aging"],
    }


# =============================================================================
# FINANCIAL REPORTS SELECTORS (P3-03)
# =============================================================================


def get_trial_balance_report(
    organization: Organization,
    *,
    as_of_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Report: Full Chart of Accounts Trial Balance with debit/credit balance equality invariant."""
    target_date = as_of_date or timezone.localdate()
    accounts = list(Account.all_tenants.filter(organization=organization).order_by("code"))

    lines_qs = JournalLine.all_tenants.filter(
        organization=organization,
        entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
        entry__date__lte=target_date,
    )

    account_totals = lines_qs.values("account_id").annotate(
        sum_debit=Sum("debit"),
        sum_credit=Sum("credit"),
    )
    totals_map = {row["account_id"]: row for row in account_totals}

    rows: list[dict[str, Any]] = []
    grand_total_debit = ZERO_DECIMAL
    grand_total_credit = ZERO_DECIMAL

    for acc in accounts:
        acc_data = totals_map.get(acc.pk, {"sum_debit": ZERO_DECIMAL, "sum_credit": ZERO_DECIMAL})
        d = acc_data["sum_debit"] or ZERO_DECIMAL
        c = acc_data["sum_credit"] or ZERO_DECIMAL

        net = d - c
        if net > ZERO_DECIMAL:
            dr_bal = net
            cr_bal = ZERO_DECIMAL
        elif net < ZERO_DECIMAL:
            dr_bal = ZERO_DECIMAL
            cr_bal = abs(net)
        else:
            dr_bal = ZERO_DECIMAL
            cr_bal = ZERO_DECIMAL

        grand_total_debit += d
        grand_total_credit += c

        rows.append(
            {
                "account_id": acc.pk,
                "code": acc.code,
                "name": acc.name,
                "type": acc.type,
                "type_display": acc.get_type_display(),
                "is_control": acc.is_control,
                "total_debit": d,
                "total_credit": c,
                "debit_balance": dr_bal,
                "credit_balance": cr_bal,
            }
        )

    difference = abs(grand_total_debit - grand_total_credit)
    is_balanced = difference == ZERO_DECIMAL

    return {
        "as_of_date": target_date,
        "rows": rows,
        "total_debit": grand_total_debit,
        "total_credit": grand_total_credit,
        "difference": difference,
        "is_balanced": is_balanced,
        "summary": {
            "account_count": len(rows),
            "total_debit": grand_total_debit,
            "total_credit": grand_total_credit,
            "difference": difference,
            "is_balanced": is_balanced,
        },
    }


def get_profit_and_loss_report(
    organization: Organization,
    *,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    """Report: Profit & Loss (Income Statement) with revenues, COGS, gross margin, and operating expenses."""
    lines_qs = JournalLine.all_tenants.filter(
        organization=organization,
        entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
        entry__date__gte=start_date,
        entry__date__lte=end_date,
    )

    account_totals = lines_qs.values("account_id").annotate(
        sum_debit=Sum("debit"),
        sum_credit=Sum("credit"),
    )
    totals_map = {row["account_id"]: row for row in account_totals}

    cogs_mappings = set(
        AccountMapping.all_tenants.filter(organization=organization, mapping_key="cogs").values_list(
            "account_id", flat=True
        )
    )

    all_accounts = Account.all_tenants.filter(
        organization=organization,
        type__in=[AccountType.REVENUE, AccountType.EXPENSE],
    ).order_by("code")

    revenue_rows: list[dict[str, Any]] = []
    cogs_rows: list[dict[str, Any]] = []
    expense_rows: list[dict[str, Any]] = []

    total_revenue = ZERO_DECIMAL
    total_cogs = ZERO_DECIMAL
    total_expenses = ZERO_DECIMAL

    for acc in all_accounts:
        acc_data = totals_map.get(acc.pk, {"sum_debit": ZERO_DECIMAL, "sum_credit": ZERO_DECIMAL})
        d = acc_data["sum_debit"] or ZERO_DECIMAL
        c = acc_data["sum_credit"] or ZERO_DECIMAL

        if d == ZERO_DECIMAL and c == ZERO_DECIMAL:
            continue

        if acc.type == AccountType.REVENUE:
            net_rev = c - d
            total_revenue += net_rev
            revenue_rows.append(
                {
                    "account_id": acc.pk,
                    "code": acc.code,
                    "name": acc.name,
                    "amount": net_rev,
                }
            )
        elif acc.type == AccountType.EXPENSE:
            net_exp = d - c
            is_cogs = (
                acc.pk in cogs_mappings
                or acc.code.startswith("5")
                or "cost of goods" in acc.name.lower()
                or "cogs" in acc.name.lower()
            )
            if is_cogs:
                total_cogs += net_exp
                cogs_rows.append(
                    {
                        "account_id": acc.pk,
                        "code": acc.code,
                        "name": acc.name,
                        "amount": net_exp,
                    }
                )
            else:
                total_expenses += net_exp
                expense_rows.append(
                    {
                        "account_id": acc.pk,
                        "code": acc.code,
                        "name": acc.name,
                        "amount": net_exp,
                    }
                )

    gross_profit = total_revenue - total_cogs
    gross_margin_pct = (
        (gross_profit / total_revenue * Decimal("100.00")).quantize(Decimal("0.01"))
        if total_revenue > ZERO_DECIMAL
        else ZERO_DECIMAL
    )

    net_profit = gross_profit - total_expenses
    net_margin_pct = (
        (net_profit / total_revenue * Decimal("100.00")).quantize(Decimal("0.01"))
        if total_revenue > ZERO_DECIMAL
        else ZERO_DECIMAL
    )

    return {
        "period": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "revenue_rows": revenue_rows,
        "total_revenue": total_revenue,
        "cogs_rows": cogs_rows,
        "total_cogs": total_cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "expense_rows": expense_rows,
        "total_expenses": total_expenses,
        "total_operating_expenses": total_expenses,
        "net_profit": net_profit,
        "net_margin_pct": net_margin_pct,
    }


def _process_balance_sheet_accounts(
    accounts: list[Account], totals_map: dict[Any, dict[str, Any]]
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    Decimal,
    list[dict[str, Any]],
    list[dict[str, Any]],
    Decimal,
    list[dict[str, Any]],
    Decimal,
    Decimal,
]:
    current_assets: list[dict[str, Any]] = []
    non_current_assets: list[dict[str, Any]] = []
    total_assets = ZERO_DECIMAL

    current_liabilities: list[dict[str, Any]] = []
    non_current_liabilities: list[dict[str, Any]] = []
    total_liabilities = ZERO_DECIMAL

    equity_rows: list[dict[str, Any]] = []
    total_base_equity = ZERO_DECIMAL

    cumulative_revenue = ZERO_DECIMAL
    cumulative_expenses = ZERO_DECIMAL

    for acc in accounts:
        acc_data = totals_map.get(acc.pk, {"sum_debit": ZERO_DECIMAL, "sum_credit": ZERO_DECIMAL})
        d = acc_data["sum_debit"] or ZERO_DECIMAL
        c = acc_data["sum_credit"] or ZERO_DECIMAL

        if acc.type == AccountType.REVENUE:
            cumulative_revenue += c - d
            continue
        if acc.type == AccountType.EXPENSE:
            cumulative_expenses += d - c
            continue

        if d == ZERO_DECIMAL and c == ZERO_DECIMAL:
            continue

        if acc.type == AccountType.ASSET:
            net_bal = d - c
            total_assets += net_bal
            row = {"account_id": acc.pk, "code": acc.code, "name": acc.name, "amount": net_bal}
            is_curr = acc.code.startswith(("10", "11", "12", "13", "14"))
            target = current_assets if is_curr else non_current_assets
            target.append(row)

        elif acc.type == AccountType.LIABILITY:
            net_bal = c - d
            total_liabilities += net_bal
            row = {"account_id": acc.pk, "code": acc.code, "name": acc.name, "amount": net_bal}
            is_curr = acc.code.startswith(("20", "21", "22"))
            target = current_liabilities if is_curr else non_current_liabilities
            target.append(row)

        elif acc.type == AccountType.EQUITY:
            net_bal = c - d
            total_base_equity += net_bal
            equity_rows.append({"account_id": acc.pk, "code": acc.code, "name": acc.name, "amount": net_bal})

    retained_earnings = cumulative_revenue - cumulative_expenses
    return (
        current_assets,
        non_current_assets,
        total_assets,
        current_liabilities,
        non_current_liabilities,
        total_liabilities,
        equity_rows,
        total_base_equity,
        retained_earnings,
    )


def get_balance_sheet_report(
    organization: Organization,
    *,
    as_of_date: datetime.date,
) -> dict[str, Any]:
    """Report: Balance Sheet showing Assets, Liabilities, and Equity with accounting equation invariant."""
    lines_qs = JournalLine.all_tenants.filter(
        organization=organization,
        entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
        entry__date__lte=as_of_date,
    )

    account_totals = lines_qs.values("account_id").annotate(
        sum_debit=Sum("debit"),
        sum_credit=Sum("credit"),
    )
    totals_map = {row["account_id"]: row for row in account_totals}
    accounts = list(Account.all_tenants.filter(organization=organization).order_by("code"))

    (
        current_assets,
        non_current_assets,
        total_assets,
        current_liabilities,
        non_current_liabilities,
        total_liabilities,
        equity_rows,
        total_base_equity,
        retained_earnings,
    ) = _process_balance_sheet_accounts(accounts, totals_map)

    total_equity = total_base_equity + retained_earnings

    total_liabilities_and_equity = total_liabilities + total_equity
    variance = abs(total_assets - total_liabilities_and_equity)
    is_balanced = variance == ZERO_DECIMAL

    return {
        "as_of_date": as_of_date,
        "current_assets": current_assets,
        "total_current_assets": sum((r["amount"] for r in current_assets), ZERO_DECIMAL),
        "non_current_assets": non_current_assets,
        "total_non_current_assets": sum((r["amount"] for r in non_current_assets), ZERO_DECIMAL),
        "total_assets": total_assets,
        "current_liabilities": current_liabilities,
        "total_current_liabilities": sum((r["amount"] for r in current_liabilities), ZERO_DECIMAL),
        "non_current_liabilities": non_current_liabilities,
        "total_non_current_liabilities": sum((r["amount"] for r in non_current_liabilities), ZERO_DECIMAL),
        "total_liabilities": total_liabilities,
        "equity_rows": equity_rows,
        "total_base_equity": total_base_equity,
        "retained_earnings": retained_earnings,
        "net_income": retained_earnings,
        "total_equity": total_equity,
        "total_liabilities_and_equity": total_liabilities_and_equity,
        "variance": variance,
        "is_balanced": is_balanced,
        "assets": {
            "current": [dict(r, balance=r["amount"]) for r in current_assets],
            "non_current": [dict(r, balance=r["amount"]) for r in non_current_assets],
            "total": total_assets,
        },
        "liabilities": {
            "current": [dict(r, balance=r["amount"]) for r in current_liabilities],
            "non_current": [dict(r, balance=r["amount"]) for r in non_current_liabilities],
            "total": total_liabilities,
        },
        "equity": {
            "rows": [dict(r, balance=r["amount"]) for r in equity_rows],
            "total": total_equity,
        },
    }


def get_cash_flow_statement_report(
    organization: Organization,
    *,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    """Report: Cash Flow Statement showing operating, investing, and financing cash activities."""
    cash_bank_accounts = list(
        Account.all_tenants.filter(
            organization=organization,
            type=AccountType.ASSET,
            code__startswith="10",
        ).values_list("id", flat=True)
    )
    linked_gl_ids = list(
        BankAccount.all_tenants.filter(organization=organization).values_list("gl_account_id", flat=True)
    )
    all_cash_account_ids = set(cash_bank_accounts) | set(linked_gl_ids)

    prior_lines = JournalLine.all_tenants.filter(
        organization=organization,
        account_id__in=all_cash_account_ids,
        entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
        entry__date__lt=start_date,
    ).aggregate(sum_debit=Sum("debit"), sum_credit=Sum("credit"))
    opening_cash = (prior_lines["sum_debit"] or ZERO_DECIMAL) - (prior_lines["sum_credit"] or ZERO_DECIMAL)

    period_lines = (
        JournalLine.all_tenants.filter(
            organization=organization,
            account_id__in=all_cash_account_ids,
            entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
            entry__date__gte=start_date,
            entry__date__lte=end_date,
        )
        .select_related("entry")
        .order_by("entry__date", "id")
    )

    inflow_customer_payments = ZERO_DECIMAL
    inflow_pos_sales = ZERO_DECIMAL
    inflow_other = ZERO_DECIMAL

    outflow_supplier_payments = ZERO_DECIMAL
    outflow_expenses = ZERO_DECIMAL
    outflow_other = ZERO_DECIMAL

    investing_flows = ZERO_DECIMAL
    financing_flows = ZERO_DECIMAL

    for line in period_lines:
        source_type = line.entry.source_type or ""
        net_flow = line.debit - line.credit

        if net_flow >= ZERO_DECIMAL:
            if "pos" in source_type:
                inflow_pos_sales += net_flow
            elif "payment" in source_type or "customer" in source_type or "invoice" in source_type:
                inflow_customer_payments += net_flow
            else:
                inflow_other += net_flow
        else:
            outflow_abs = abs(net_flow)
            if "supplier" in source_type or "bill" in source_type or "purchase" in source_type:
                outflow_supplier_payments += outflow_abs
            elif "expense" in source_type:
                outflow_expenses += outflow_abs
            else:
                outflow_other += outflow_abs

    total_operating_inflows = inflow_customer_payments + inflow_pos_sales + inflow_other
    total_operating_outflows = outflow_supplier_payments + outflow_expenses + outflow_other
    net_operating_cash = total_operating_inflows - total_operating_outflows

    net_cash_change = net_operating_cash + investing_flows + financing_flows
    closing_cash = opening_cash + net_cash_change

    return {
        "period": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "opening_cash": opening_cash,
        "operating_activities": {
            "inflows": {
                "customer_payments": inflow_customer_payments,
                "pos_sales": inflow_pos_sales,
                "other": inflow_other,
                "total": total_operating_inflows,
            },
            "outflows": {
                "supplier_payments": outflow_supplier_payments,
                "expenses": outflow_expenses,
                "other": outflow_other,
                "total": total_operating_outflows,
            },
            "net": net_operating_cash,
        },
        "investing_activities": {
            "net": investing_flows,
        },
        "financing_activities": {
            "net": financing_flows,
        },
        "net_cash_change": net_cash_change,
        "closing_cash": closing_cash,
    }


get_cash_flow_report = get_cash_flow_statement_report


def get_general_ledger_report(
    organization: Organization,
    *,
    start_date: datetime.date,
    end_date: datetime.date,
    account_id: int | None = None,
) -> dict[str, Any]:
    """Report: General Ledger transaction audit report by account with running balances."""
    acc_qs = Account.all_tenants.filter(organization=organization).order_by("code")
    if account_id:
        acc_qs = acc_qs.filter(pk=account_id)
    accounts = list(acc_qs)

    account_reports: list[dict[str, Any]] = []
    grand_total_debit = ZERO_DECIMAL
    grand_total_credit = ZERO_DECIMAL

    for acc in accounts:
        prior_agg = JournalLine.all_tenants.filter(
            organization=organization,
            account=acc,
            entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
            entry__date__lt=start_date,
        ).aggregate(sum_debit=Sum("debit"), sum_credit=Sum("credit"))

        d_prior = prior_agg["sum_debit"] or ZERO_DECIMAL
        c_prior = prior_agg["sum_credit"] or ZERO_DECIMAL
        opening_bal = (d_prior - c_prior) if acc.is_debit_normal else (c_prior - d_prior)

        period_lines = (
            JournalLine.all_tenants.filter(
                organization=organization,
                account=acc,
                entry__status__in=[JournalEntry.STATUS_POSTED, JournalEntry.STATUS_REVERSED],
                entry__date__gte=start_date,
                entry__date__lte=end_date,
            )
            .select_related("entry")
            .order_by("entry__date", "entry__id", "id")
        )

        running_bal = opening_bal
        lines_data: list[dict[str, Any]] = []
        period_debit = ZERO_DECIMAL
        period_credit = ZERO_DECIMAL

        for line in period_lines:
            period_debit += line.debit
            period_credit += line.credit

            if acc.is_debit_normal:
                running_bal += line.debit - line.credit
            else:
                running_bal += line.credit - line.debit

            lines_data.append(
                {
                    "date": line.entry.date,
                    "entry_number": line.entry.entry_number,
                    "memo": getattr(line, "memo", "") or getattr(line.entry, "memo", "") or "-",
                    "source_type": line.entry.source_type or "-",
                    "source_id": line.entry.source_id or "-",
                    "debit": line.debit,
                    "credit": line.credit,
                    "running_balance": running_bal,
                }
            )

        if not lines_data and opening_bal == ZERO_DECIMAL:
            continue

        grand_total_debit += period_debit
        grand_total_credit += period_credit

        account_reports.append(
            {
                "account_id": acc.pk,
                "code": acc.code,
                "name": acc.name,
                "type": acc.type,
                "type_display": acc.get_type_display(),
                "normal_balance": "Debit" if acc.is_debit_normal else "Credit",
                "opening_balance": opening_bal,
                "lines": lines_data,
                "period_debit": period_debit,
                "period_credit": period_credit,
                "closing_balance": running_bal,
            }
        )

    return {
        "period": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "accounts": account_reports,
        "grand_total_debit": grand_total_debit,
        "grand_total_credit": grand_total_credit,
    }


def get_aged_receivables_report(
    organization: Organization,
    *,
    as_of_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Report: Accounts Receivable Aging analysis (Current, 1-30, 31-60, 61-90, 91+ days)."""
    target_date = as_of_date or timezone.localdate()

    invoices = (
        Invoice.all_tenants.filter(
            organization=organization,
            status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
            invoice_date__lte=target_date,
        )
        .select_related("customer")
        .order_by("customer__name", "due_date")
    )

    customers_map: dict[int, dict[str, Any]] = {}
    total_current = ZERO_DECIMAL
    total_1_30 = ZERO_DECIMAL
    total_31_60 = ZERO_DECIMAL
    total_61_90 = ZERO_DECIMAL
    total_90_plus = ZERO_DECIMAL
    grand_total_due = ZERO_DECIMAL

    for inv in invoices:
        due = getattr(inv, "balance_due", None)
        if due is None:
            total_val = getattr(inv, "grand_total", getattr(inv, "total", ZERO_DECIMAL))
            paid_val = getattr(inv, "amount_paid", ZERO_DECIMAL)
            due = total_val - paid_val
        if due <= ZERO_DECIMAL:
            continue

        due_date = inv.due_date or inv.invoice_date
        overdue_days = (target_date - due_date).days

        cust = inv.customer
        if cust.pk not in customers_map:
            customers_map[cust.pk] = {
                "customer_id": cust.pk,
                "customer_name": cust.name,
                "code": getattr(cust, "code", ""),
                "name": cust.name,
                "current": ZERO_DECIMAL,
                "bucket_current": ZERO_DECIMAL,
                "days_1_30": ZERO_DECIMAL,
                "bucket_1_30": ZERO_DECIMAL,
                "bucket_30": ZERO_DECIMAL,
                "days_31_60": ZERO_DECIMAL,
                "bucket_31_60": ZERO_DECIMAL,
                "bucket_60": ZERO_DECIMAL,
                "days_61_90": ZERO_DECIMAL,
                "bucket_61_90": ZERO_DECIMAL,
                "bucket_90": ZERO_DECIMAL,
                "days_90_plus": ZERO_DECIMAL,
                "bucket_90_plus": ZERO_DECIMAL,
                "total_due": ZERO_DECIMAL,
                "total": ZERO_DECIMAL,
            }

        rec = customers_map[cust.pk]
        if overdue_days <= 0:
            rec["current"] += due
            rec["bucket_current"] += due
            total_current += due
        elif 1 <= overdue_days <= 30:
            rec["days_1_30"] += due
            rec["bucket_1_30"] += due
            rec["bucket_30"] += due
            total_1_30 += due
        elif 31 <= overdue_days <= 60:
            rec["days_31_60"] += due
            rec["bucket_31_60"] += due
            rec["bucket_60"] += due
            total_31_60 += due
        elif 61 <= overdue_days <= 90:
            rec["days_61_90"] += due
            rec["bucket_61_90"] += due
            rec["bucket_90"] += due
            total_61_90 += due
        else:
            rec["days_90_plus"] += due
            rec["bucket_90_plus"] += due
            total_90_plus += due

        rec["total_due"] += due
        rec["total"] += due
        grand_total_due += due

    rows = sorted(customers_map.values(), key=lambda r: r["name"])

    return {
        "as_of_date": target_date,
        "rows": rows,
        "summary": {
            "customer_count": len(rows),
            "total_current": total_current,
            "total_1_30": total_1_30,
            "total_31_60": total_31_60,
            "total_61_90": total_61_90,
            "total_90_plus": total_90_plus,
            "grand_total_due": grand_total_due,
            "grand_total": grand_total_due,
        },
    }


def get_aged_payables_report(
    organization: Organization,
    *,
    as_of_date: datetime.date | None = None,
) -> dict[str, Any]:
    """Report: Accounts Payable Aging analysis (Current, 1-30, 31-60, 61-90, 91+ days)."""
    target_date = as_of_date or timezone.localdate()

    bills = (
        SupplierBill.all_tenants.filter(
            organization=organization,
            status__in=[SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID],
            issue_date__lte=target_date,
        )
        .select_related("supplier")
        .order_by("supplier__name", "due_date")
    )

    suppliers_map: dict[int, dict[str, Any]] = {}
    total_current = ZERO_DECIMAL
    total_1_30 = ZERO_DECIMAL
    total_31_60 = ZERO_DECIMAL
    total_61_90 = ZERO_DECIMAL
    total_90_plus = ZERO_DECIMAL
    grand_total_due = ZERO_DECIMAL

    for bill in bills:
        due = getattr(bill, "balance_due", None)
        if due is None:
            total_val = getattr(
                bill, "total_amount", getattr(bill, "grand_total", getattr(bill, "total", ZERO_DECIMAL))
            )
            paid_val = getattr(bill, "amount_paid", ZERO_DECIMAL)
            due = total_val - paid_val
        if due <= ZERO_DECIMAL:
            continue

        due_date = bill.due_date or bill.issue_date
        overdue_days = (target_date - due_date).days

        sup = bill.supplier
        if sup.pk not in suppliers_map:
            suppliers_map[sup.pk] = {
                "supplier_id": sup.pk,
                "supplier_name": sup.name,
                "code": getattr(sup, "code", ""),
                "name": sup.name,
                "current": ZERO_DECIMAL,
                "bucket_current": ZERO_DECIMAL,
                "days_1_30": ZERO_DECIMAL,
                "bucket_1_30": ZERO_DECIMAL,
                "bucket_30": ZERO_DECIMAL,
                "days_31_60": ZERO_DECIMAL,
                "bucket_31_60": ZERO_DECIMAL,
                "bucket_60": ZERO_DECIMAL,
                "days_61_90": ZERO_DECIMAL,
                "bucket_61_90": ZERO_DECIMAL,
                "bucket_90": ZERO_DECIMAL,
                "days_90_plus": ZERO_DECIMAL,
                "bucket_90_plus": ZERO_DECIMAL,
                "total_due": ZERO_DECIMAL,
                "total": ZERO_DECIMAL,
            }

        rec = suppliers_map[sup.pk]
        if overdue_days <= 0:
            rec["current"] += due
            rec["bucket_current"] += due
            total_current += due
        elif 1 <= overdue_days <= 30:
            rec["days_1_30"] += due
            rec["bucket_1_30"] += due
            rec["bucket_30"] += due
            total_1_30 += due
        elif 31 <= overdue_days <= 60:
            rec["days_31_60"] += due
            rec["bucket_31_60"] += due
            rec["bucket_60"] += due
            total_31_60 += due
        elif 61 <= overdue_days <= 90:
            rec["days_61_90"] += due
            rec["bucket_61_90"] += due
            rec["bucket_90"] += due
            total_61_90 += due
        else:
            rec["days_90_plus"] += due
            rec["bucket_90_plus"] += due
            total_90_plus += due

        rec["total_due"] += due
        rec["total"] += due
        grand_total_due += due

    rows = sorted(suppliers_map.values(), key=lambda r: r["name"])

    return {
        "as_of_date": target_date,
        "rows": rows,
        "summary": {
            "supplier_count": len(rows),
            "total_current": total_current,
            "total_1_30": total_1_30,
            "total_31_60": total_31_60,
            "total_61_90": total_61_90,
            "total_90_plus": total_90_plus,
            "grand_total_due": grand_total_due,
            "grand_total": grand_total_due,
        },
    }


def get_tax_summary_report(
    organization: Organization,
    *,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    """Report: Tax Summary aggregating Output Tax, Input Tax, and Net Tax Liability."""
    inv_qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID],
        invoice_date__gte=start_date,
        invoice_date__lte=end_date,
    )
    inv_agg = inv_qs.aggregate(total_taxable=Sum("subtotal"), total_tax=Sum("tax_total"))
    sales_taxable = inv_agg["total_taxable"] or ZERO_DECIMAL
    output_tax = inv_agg["total_tax"] or ZERO_DECIMAL

    bill_qs = SupplierBill.all_tenants.filter(
        organization=organization,
        status__in=[SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID, SupplierBillStatus.PAID],
        issue_date__gte=start_date,
        issue_date__lte=end_date,
    )
    bill_agg = bill_qs.aggregate(total_taxable=Sum("subtotal"), total_tax=Sum("tax_total"))
    purchases_taxable = bill_agg["total_taxable"] or ZERO_DECIMAL
    purchases_tax = bill_agg["total_tax"] or ZERO_DECIMAL

    exp_qs = Expense.all_tenants.filter(
        organization=organization,
        status=ExpenseStatus.POSTED,
        date__gte=start_date,
        date__lte=end_date,
    )
    exp_agg = exp_qs.aggregate(
        total_taxable=Sum(F("total_amount") - F("tax_amount")),
        total_tax=Sum("tax_amount"),
    )
    expenses_taxable = exp_agg["total_taxable"] or ZERO_DECIMAL
    expenses_tax = exp_agg["total_tax"] or ZERO_DECIMAL

    total_input_tax = purchases_tax + expenses_tax
    net_tax_payable = output_tax - total_input_tax

    return {
        "period": {
            "start_date": start_date,
            "end_date": end_date,
        },
        "output_tax": {
            "sales_taxable": sales_taxable,
            "output_tax_collected": output_tax,
            "tax_amount": output_tax,
            "invoice_count": inv_qs.count(),
        },
        "input_tax": {
            "purchases_taxable": purchases_taxable,
            "purchases_tax_paid": purchases_tax,
            "bill_count": bill_qs.count(),
            "expenses_taxable": expenses_taxable,
            "expenses_tax_paid": expenses_tax,
            "expense_count": exp_qs.count(),
            "total_input_tax": total_input_tax,
            "tax_amount": total_input_tax,
        },
        "summary": {
            "total_output_tax": output_tax,
            "total_input_tax": total_input_tax,
            "net_tax_payable": net_tax_payable,
            "is_refund": net_tax_payable < ZERO_DECIMAL,
            "is_payable": net_tax_payable >= ZERO_DECIMAL,
        },
        "net_tax_payable": net_tax_payable,
        "is_payable": net_tax_payable >= ZERO_DECIMAL,
    }
