"""Read-only selectors for customer accounts, balance ledgers, and statement generation."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from django.db.models import F, Q, QuerySet, Sum
from django.utils import timezone

from apps.customers.models import Customer, CustomerBalanceEntry, CustomerStatus
from apps.tenancy.models import Organization


def get_customers(
    *,
    organization: Organization,
    query: str = "",
    status: str = "",
    type: str = "",
    has_balance_only: bool = False,
    over_credit_only: bool = False,
    order_by: str = "name",
) -> QuerySet[Customer]:
    """Return filtered queryset of customers scoped to organization."""
    qs = (
        Customer.all_tenants.filter(organization=organization)
        .select_related("price_list")
        .prefetch_related("contacts")
    )

    if query:
        q_clean = query.strip()
        qs = qs.filter(
            Q(name__icontains=q_clean)
            | Q(code__icontains=q_clean)
            | Q(email__icontains=q_clean)
            | Q(phone__icontains=q_clean)
            | Q(tax_id__icontains=q_clean)
        )

    if status:
        qs = qs.filter(status=status)

    if type:
        qs = qs.filter(type=type)

    if has_balance_only:
        qs = qs.filter(current_balance__gt=Decimal("0.0000"))

    if over_credit_only:
        qs = qs.filter(credit_limit__gt=Decimal("0.0000"), current_balance__gt=F("credit_limit"))

    valid_orders = {
        "name": "name",
        "-name": "-name",
        "code": "code",
        "-code": "-code",
        "balance": "-current_balance",
        "-balance": "current_balance",
        "created": "-created_at",
    }
    sort_field = valid_orders.get(order_by, "name")
    return qs.order_by(sort_field)


def get_customer_by_id(*, organization: Organization, customer_id: int) -> Customer | None:
    """Retrieve single customer by internal ID with related entities."""
    return (
        Customer.all_tenants.filter(organization=organization, pk=customer_id)
        .select_related("price_list")
        .prefetch_related("addresses", "contacts")
        .first()
    )


def get_customer_by_public_id(
    *,
    organization: Organization,
    public_id: uuid.UUID | str,
) -> Customer | None:
    """Retrieve single customer by external public UUID."""
    return (
        Customer.all_tenants.filter(organization=organization, public_id=public_id)
        .select_related("price_list")
        .prefetch_related("addresses", "contacts")
        .first()
    )


def get_customer_balance_ledger(
    *,
    organization: Organization,
    customer: Customer,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> QuerySet[CustomerBalanceEntry]:
    """Return chronological subledger entries for a customer."""
    qs = CustomerBalanceEntry.all_tenants.filter(
        organization=organization,
        customer=customer,
    )
    if start_date:
        qs = qs.filter(occurred_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(occurred_at__date__lte=end_date)

    return qs.order_by("-occurred_at", "-id")


def get_customer_statement(
    *,
    organization: Organization,
    customer: Customer,
    start_date: datetime.date,
    end_date: datetime.date,
) -> dict[str, Any]:
    """Generate a formal period statement with aging breakdown."""
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min), tz)
    end_dt = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max), tz)

    # 1. Opening Balance prior to start_date
    prior_totals = CustomerBalanceEntry.all_tenants.filter(
        organization=organization,
        customer=customer,
        occurred_at__lt=start_dt,
    ).aggregate(
        tot_dr=Sum("debit"),
        tot_cr=Sum("credit"),
    )
    prior_dr = prior_totals["tot_dr"] or Decimal("0.0000")
    prior_cr = prior_totals["tot_cr"] or Decimal("0.0000")
    opening_balance = prior_dr - prior_cr

    # 2. Entries in statement window
    period_entries = CustomerBalanceEntry.all_tenants.filter(
        organization=organization,
        customer=customer,
        occurred_at__gte=start_dt,
        occurred_at__lte=end_dt,
    ).order_by("occurred_at", "id")

    # 3. Running balances & totals
    running = opening_balance
    lines: list[dict[str, Any]] = []
    total_debits = Decimal("0.0000")
    total_credits = Decimal("0.0000")

    for entry in period_entries:
        running += entry.debit - entry.credit
        total_debits += entry.debit
        total_credits += entry.credit
        lines.append(
            {
                "entry": entry,
                "running_balance": running,
            }
        )

    closing_balance = opening_balance + total_debits - total_credits

    # 4. Aging breakdown based on open unpaid invoices
    aging = {
        "current": Decimal("0.0000"),
        "days_1_30": Decimal("0.0000"),
        "days_31_60": Decimal("0.0000"),
        "days_61_90": Decimal("0.0000"),
        "days_over_90": Decimal("0.0000"),
    }

    # Aggregate debit entries within buckets
    all_debits = CustomerBalanceEntry.all_tenants.filter(
        organization=organization,
        customer=customer,
        debit__gt=Decimal("0.0000"),
        occurred_at__lte=end_dt,
    ).order_by("-occurred_at")

    remaining_due = max(Decimal("0.0000"), closing_balance)
    for d in all_debits:
        if remaining_due <= Decimal("0.0000"):
            break
        age_days = (end_date - d.occurred_at.date()).days
        portion = min(remaining_due, d.debit)

        if age_days <= 30:
            aging["current"] += portion
        elif age_days <= 60:
            aging["days_1_30"] += portion
        elif age_days <= 90:
            aging["days_31_60"] += portion
        elif age_days <= 120:
            aging["days_61_90"] += portion
        else:
            aging["days_over_90"] += portion

        remaining_due -= portion

    return {
        "customer": customer,
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance": opening_balance,
        "total_debits": total_debits,
        "total_credits": total_credits,
        "closing_balance": closing_balance,
        "lines": lines,
        "aging": aging,
    }


def get_customer_overview_metrics(*, organization: Organization) -> dict[str, Any]:
    """Return dashboard summary metrics for customer receivables."""
    all_custs = Customer.all_tenants.filter(organization=organization)
    total_count = all_custs.count()
    active_count = all_custs.filter(status=CustomerStatus.ACTIVE).count()

    totals = all_custs.filter(current_balance__gt=Decimal("0.0000")).aggregate(
        total_ar=Sum("current_balance")
    )
    total_ar = totals["total_ar"] or Decimal("0.0000")

    over_credit_count = all_custs.filter(
        credit_limit__gt=Decimal("0.0000"),
        current_balance__gt=F("credit_limit"),
    ).count()

    return {
        "total_customers": total_count,
        "active_customers": active_count,
        "total_receivables": total_ar,
        "over_credit_count": over_credit_count,
    }
