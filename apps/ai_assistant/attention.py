"""Attention Engine: Rule-based operational detectors and AI executive briefing synthesizer."""

from __future__ import annotations

import datetime
import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.ai_assistant.permissions import user_has_ai_permission
from apps.ai_assistant.providers.base import AiChatMessage
from apps.ai_assistant.providers.factory import get_ai_provider
from apps.approvals.constants import ApprovalStatus
from apps.approvals.models import ApprovalRequest
from apps.customers.models import Customer
from apps.inventory.models import StockLevel
from apps.purchasing.models import SupplierBill, SupplierBillStatus
from apps.sales.models import Invoice, InvoiceStatus, Quote, QuoteStatus, SalesOrder, SalesOrderStatus
from apps.tenancy.models import Organization

logger = logging.getLogger(__name__)


@dataclass
class AttentionItem:
    """A structured operational insight requiring attention."""

    id: str
    title: str
    description: str
    category: str  # "finance", "inventory", "sales", "approvals", "customers"
    severity: str  # "critical", "warning", "info"
    count: int
    metric: str
    action_url: str
    action_label: str
    details: dict[str, Any] = field(default_factory=dict)
    icon: str = "alert"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# =============================================================================
# Rule-Based Operational Detectors
# =============================================================================


def detect_overdue_receivables(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect unpaid customer sales invoices past due date."""
    if not user_has_ai_permission(user, organization.pk, "sales.view"):
        return None

    today = timezone.now().date()
    qs = Invoice.all_tenants.filter(
        organization=organization,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PARTIALLY_PAID],
        due_date__lt=today,
        balance_due__gt=Decimal("0.0000"),
    ).order_by("due_date")

    count = qs.count()
    if count == 0:
        return None

    total_overdue = qs.aggregate(tot=Sum("balance_due"))["tot"] or Decimal("0.00")
    oldest = qs.first()
    days_overdue = (today - oldest.due_date).days if oldest and oldest.due_date else 0
    severity = "critical" if days_overdue >= 14 or count >= 5 else "warning"

    customer_name = oldest.customer.name if oldest and oldest.customer else _("Customer")
    desc = _(
        "%(count)d invoice(s) overdue totaling $%(amount)s. Oldest: %(days)d days past due (%(cust)s)."
    ) % {
        "count": count,
        "amount": f"{total_overdue:,.2f}",
        "days": days_overdue,
        "cust": customer_name,
    }

    return AttentionItem(
        id="overdue_receivables",
        title=_("Overdue Customer Invoices"),
        description=desc,
        category="finance",
        severity=severity,
        count=count,
        metric=f"${total_overdue:,.2f}",
        action_url="/sales/invoices/?status=overdue",
        action_label=_("Review Invoices"),
        details={
            "total_overdue": str(total_overdue),
            "oldest_invoice_id": oldest.pk if oldest else None,
            "days_overdue": days_overdue,
        },
        icon="currency-dollar",
    )


def detect_overdue_payables(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect unpaid supplier bills that are overdue."""
    if not user_has_ai_permission(user, organization.pk, "purchasing.view"):
        return None

    today = timezone.now().date()
    qs = SupplierBill.all_tenants.filter(
        organization=organization,
        status__in=[SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID],
        due_date__lt=today,
        balance_due__gt=Decimal("0.0000"),
    ).order_by("due_date")

    count = qs.count()
    if count == 0:
        return None

    total_due = qs.aggregate(tot=Sum("balance_due"))["tot"] or Decimal("0.00")
    oldest = qs.first()
    days_overdue = (today - oldest.due_date).days if oldest and oldest.due_date else 0
    severity = "critical" if days_overdue >= 14 else "warning"

    supplier_name = oldest.supplier.name if oldest and oldest.supplier else _("Vendor")
    desc = _(
        "%(count)d vendor bill(s) past due totaling $%(amount)s. Oldest: %(days)d days past due to %(supp)s."
    ) % {
        "count": count,
        "amount": f"{total_due:,.2f}",
        "days": days_overdue,
        "supp": supplier_name,
    }

    return AttentionItem(
        id="overdue_payables",
        title=_("Overdue Supplier Payables"),
        description=desc,
        category="finance",
        severity=severity,
        count=count,
        metric=f"${total_due:,.2f}",
        action_url="/purchasing/bills/?status=overdue",
        action_label=_("Manage Payables"),
        details={
            "total_due": str(total_due),
            "oldest_bill_id": oldest.pk if oldest else None,
        },
        icon="credit-card",
    )


def detect_low_stock(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect stock items with zero quantity (stockout) or below reorder threshold."""
    if not user_has_ai_permission(user, organization.pk, "inventory.view"):
        return None

    # Check stockouts first
    stockouts = StockLevel.all_tenants.filter(
        organization=organization,
        on_hand__lte=Decimal("0.0000"),
    ).select_related("product")
    stockout_count = stockouts.count()

    # Check low stock below reorder point
    all_levels = (
        StockLevel.all_tenants.filter(
            organization=organization,
        )
        .select_related("product")
        .exclude(reorder_point=None)
    )

    low_items: list[StockLevel] = []
    for sl in all_levels:
        if sl.reorder_point is not None and sl.on_hand <= sl.reorder_point:
            low_items.append(sl)

    total_low = len(low_items)
    if total_low == 0 and stockout_count == 0:
        return None

    severity = "critical" if stockout_count > 0 else "warning"
    first_stockout = stockouts.first() if stockout_count > 0 else None
    sample_prod = first_stockout.product.name if first_stockout else ""
    if not sample_prod and low_items:
        sample_prod = low_items[0].product.name

    desc = _(
        "%(stockout)d items completely out of stock; "
        "%(low)d items below safety reorder threshold (e.g. %(prod)s)."
    ) % {
        "stockout": stockout_count,
        "low": total_low,
        "prod": sample_prod or _("Inventory items"),
    }

    return AttentionItem(
        id="low_stock_alerts",
        title=_("Stockout & Reorder Alerts"),
        description=desc,
        category="inventory",
        severity=severity,
        count=stockout_count + total_low,
        metric=f"{stockout_count + total_low} " + _("items"),
        action_url="/inventory/stock/?filter=low",
        action_label=_("Replenish Stock"),
        details={
            "stockout_count": stockout_count,
            "reorder_count": total_low,
            "sample_product": sample_prod,
        },
        icon="exclamation-triangle",
    )


def detect_unfulfilled_orders(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect confirmed sales orders awaiting fulfillment and shipment."""
    if not user_has_ai_permission(user, organization.pk, "sales.view"):
        return None

    qs = SalesOrder.all_tenants.filter(
        organization=organization,
        status=SalesOrderStatus.CONFIRMED,
    ).order_by("order_date")

    count = qs.count()
    if count == 0:
        return None

    oldest = qs.first()
    severity = "warning" if count >= 3 else "info"
    desc = _("%(count)d confirmed order(s) awaiting warehouse picking, packaging, or shipment dispatch.") % {
        "count": count
    }

    return AttentionItem(
        id="unfulfilled_orders",
        title=_("Unfulfilled Sales Orders"),
        description=desc,
        category="sales",
        severity=severity,
        count=count,
        metric=f"{count} " + _("orders"),
        action_url="/sales/orders/?status=confirmed",
        action_label=_("Fulfill Orders"),
        details={
            "oldest_order_number": oldest.order_number if oldest else "",
        },
        icon="truck",
    )


def detect_pending_approvals(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect pending document approval requests awaiting sign-off."""
    if not user_has_ai_permission(user, organization.pk, "approvals.view"):
        return None

    qs = ApprovalRequest.all_tenants.filter(
        organization=organization,
        status=ApprovalStatus.PENDING,
    ).order_by("-created_at")

    count = qs.count()
    if count == 0:
        return None

    severity = "critical" if count >= 5 else "warning"
    latest = qs.first()
    doc_ref = latest.document_reference if latest else ""

    desc = _("%(count)d request(s) awaiting managerial review and sign-off (e.g. %(ref)s).") % {
        "count": count,
        "ref": doc_ref,
    }

    return AttentionItem(
        id="pending_approvals",
        title=_("Pending Document Approvals"),
        description=desc,
        category="approvals",
        severity=severity,
        count=count,
        metric=f"{count} " + _("pending"),
        action_url="/approvals/requests/?status=pending",
        action_label=_("Review Approvals"),
        details={
            "latest_reference": doc_ref,
        },
        icon="clipboard-document-check",
    )


def detect_expiring_quotes(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect sent customer quotes expiring within the next 3 days."""
    if not user_has_ai_permission(user, organization.pk, "sales.view"):
        return None

    today = timezone.now().date()
    window_end = today + datetime.timedelta(days=3)

    qs = Quote.all_tenants.filter(
        organization=organization,
        status=QuoteStatus.SENT,
        valid_until__gte=today,
        valid_until__lte=window_end,
    ).order_by("valid_until")

    count = qs.count()
    if count == 0:
        return None

    desc = _(
        "%(count)d sent quotation(s) will expire within the next 72 hours without customer confirmation."
    ) % {"count": count}

    return AttentionItem(
        id="expiring_quotes",
        title=_("Expiring Sales Quotes"),
        description=desc,
        category="sales",
        severity="info",
        count=count,
        metric=f"{count} " + _("quotes"),
        action_url="/sales/quotes/?status=sent",
        action_label=_("Follow Up"),
        details={"expiring_count": count},
        icon="clock",
    )


def detect_dormant_customers(organization: Organization, user: Any) -> AttentionItem | None:
    """Detect active customer accounts that have had no transaction in 60+ days."""
    if not user_has_ai_permission(user, organization.pk, "customers.view"):
        return None

    today = timezone.now().date()
    cutoff = today - datetime.timedelta(days=60)

    customers = Customer.all_tenants.filter(organization=organization, status="active")
    dormant_count = 0
    sample_name = ""

    for cust in customers[:50]:
        latest_inv = (
            Invoice.all_tenants.filter(organization=organization, customer=cust)
            .order_by("-invoice_date")
            .first()
        )
        if latest_inv and latest_inv.invoice_date <= cutoff:
            dormant_count += 1
            if not sample_name:
                sample_name = cust.name

    if dormant_count == 0:
        return None

    desc = _(
        "%(count)d previously active client account(s) have placed no orders in over 60 days (e.g. %(cust)s)."
    ) % {"count": dormant_count, "cust": sample_name}

    return AttentionItem(
        id="dormant_customers",
        title=_("Dormant Customer Accounts"),
        description=desc,
        category="customers",
        severity="info",
        count=dormant_count,
        metric=f"{dormant_count} " + _("inactive"),
        action_url="/customers/",
        action_label=_("Win-Back Campaign"),
        details={"dormant_count": dormant_count, "sample_customer": sample_name},
        icon="user-minus",
    )


# =============================================================================
# Aggregation & AI Briefing Engine
# =============================================================================


DETECTORS = [
    detect_overdue_receivables,
    detect_low_stock,
    detect_pending_approvals,
    detect_overdue_payables,
    detect_unfulfilled_orders,
    detect_expiring_quotes,
    detect_dormant_customers,
]


def get_attention_items(
    organization: Organization | int,
    user: Any,
    *,
    category: str | None = None,
    dismissed_ids: set[str] | list[str] | None = None,
) -> list[AttentionItem]:
    """Execute all operational detectors and return sorted, filtered items."""
    org = (
        organization if isinstance(organization, Organization) else Organization.objects.get(pk=organization)
    )
    dismissed = set(dismissed_ids or [])

    items: list[AttentionItem] = []
    for detector in DETECTORS:
        try:
            item = detector(org, user)
            if item and item.id not in dismissed:
                if category and category not in ("all", item.category):
                    continue
                items.append(item)
        except Exception as err:
            logger.debug("Attention detector %s failed: %s", getattr(detector, "__name__", "unknown"), err)
            continue

    # Priority sorting: critical first, then warning, then info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda x: (severity_order.get(x.severity, 3), -x.count))
    return items


def get_attention_summary(
    organization: Organization | int,
    user: Any,
    *,
    dismissed_ids: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """Retrieve full metrics breakdown and categorization of current attention items."""
    all_items = get_attention_items(organization, user, category=None, dismissed_ids=dismissed_ids)

    critical_count = sum(1 for it in all_items if it.severity == "critical")
    warning_count = sum(1 for it in all_items if it.severity == "warning")
    info_count = sum(1 for it in all_items if it.severity == "info")

    categories: dict[str, int] = {}
    for it in all_items:
        categories[it.category] = categories.get(it.category, 0) + 1

    return {
        "items": all_items,
        "total_count": len(all_items),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "categories": categories,
    }


def generate_attention_briefing(
    organization: Organization | int,
    user: Any,
    *,
    items: list[AttentionItem] | None = None,
) -> dict[str, Any]:
    """Synthesize active attention items into a concise executive morning briefing."""
    org = (
        organization if isinstance(organization, Organization) else Organization.objects.get(pk=organization)
    )
    active_items = items if items is not None else get_attention_items(org, user, category=None)

    timestamp = timezone.now().strftime("%B %d, %Y - %I:%M %p")

    if not active_items:
        return {
            "status": "success",
            "briefing": _(
                "All operational fronts are green today. "
                "No overdue invoices, stockouts, or pending approvals detected."
            ),
            "generated_at": timestamp,
            "provider": "deterministic",
            "item_count": 0,
        }

    # Construct briefing prompt
    items_bullet_list = "\n".join(
        [f"- [{it.severity.upper()}] {it.title}: {it.description}" for it in active_items]
    )

    prompt = (
        f"You are the executive copilot for {org.name}. Here are today's urgent operational alerts:\n"
        f"{items_bullet_list}\n\n"
        "Please provide a crisp 3-bullet morning briefing for the business owner:\n"
        "1. Highlight the top 1-2 critical operational risks.\n"
        "2. Note urgent financial or inventory actions needed today.\n"
        "3. Provide one concrete recommendation for prioritization."
    )

    provider = get_ai_provider()
    try:
        response = provider.chat(
            messages=[
                AiChatMessage(
                    role="system",
                    content="You are a concise, decisive executive business operations advisor.",
                ),
                AiChatMessage(role="user", content=prompt),
            ],
            model="briefing-agent",
        )
        content = response.content.strip() if response.content else ""
    except Exception:
        content = ""

    if not content or "Hello!" in content or "AI Copilot" in content:
        lines = []
        for it in active_items[:3]:
            lines.append(f"• {it.title}: {it.description}")
        content = "\n".join(lines)

    return {
        "status": "success",
        "briefing": content,
        "generated_at": timestamp,
        "provider": getattr(provider, "provider_name", "fake"),
        "item_count": len(active_items),
    }
