"""Business Analytics Engine.

Provides deep operational analytics across customer retention cohorts,
Pareto ABC product rationalization, gross profit margins, and moving-average
inventory demand replenishment forecasting.
"""

from __future__ import annotations

import datetime
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product, ProductType
from apps.inventory.models import StockLevel
from apps.sales.models import Invoice, InvoiceLine, InvoiceStatus
from apps.tenancy.models import Organization

# =============================================================================
# 1. Customer Cohort & Retention Analysis
# =============================================================================


@dataclass
class CohortPeriodData:
    period: int  # Month 0, 1, 2, ...
    active_customers: int
    retention_rate: float  # Percentage (0.0 to 100.0)
    revenue: Decimal

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["revenue"] = str(self.revenue)
        return d


@dataclass
class CustomerCohort:
    cohort_month: str  # "YYYY-MM"
    cohort_size: int  # Total customers acquired in this month
    total_cohort_revenue: Decimal
    periods: list[CohortPeriodData] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_month": self.cohort_month,
            "cohort_size": self.cohort_size,
            "total_cohort_revenue": str(self.total_cohort_revenue),
            "periods": [p.to_dict() for p in self.periods],
        }


@dataclass
class CohortAnalysisResult:
    cohorts: list[CustomerCohort]
    total_customers: int
    total_cohorts: int
    avg_m1_retention: float
    total_lifetime_revenue: Decimal
    periods_header: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohorts": [c.to_dict() for c in self.cohorts],
            "total_customers": self.total_customers,
            "total_cohorts": self.total_cohorts,
            "avg_m1_retention": self.avg_m1_retention,
            "total_lifetime_revenue": str(self.total_lifetime_revenue),
            "periods_header": self.periods_header,
        }


def _group_customer_first_purchases(invoices: list[dict[str, Any]]) -> dict[int, datetime.date]:
    """Map each customer to the date of their earliest invoice."""
    first_months: dict[int, datetime.date] = {}
    for inv in invoices:
        cid = inv["customer_id"]
        inv_date = inv["invoice_date"]
        if cid not in first_months or inv_date < first_months[cid]:
            first_months[cid] = inv_date
    return first_months


def _build_cohort_activity_map(
    invoices: list[dict[str, Any]],
    customer_cohort_key: dict[int, str],
    customer_first_month: dict[int, datetime.date],
    max_periods: int,
) -> tuple[dict[str, dict[int, dict[str, Any]]], Decimal]:
    """Aggregate customer activity and spend across cohorts and relative month periods."""
    activity_map: dict[str, dict[int, dict[str, Any]]] = {}
    total_revenue = Decimal("0.00")

    for inv in invoices:
        cid = inv["customer_id"]
        inv_date: datetime.date = inv["invoice_date"]
        amt: Decimal = Decimal(str(inv["grand_total"] or "0.00"))
        total_revenue += amt

        ckey = customer_cohort_key.get(cid)
        if not ckey:
            continue

        first_d = customer_first_month[cid]
        period_idx = max(0, (inv_date.year - first_d.year) * 12 + (inv_date.month - first_d.month))
        if period_idx >= max_periods:
            continue

        cohort_periods = activity_map.setdefault(ckey, {})
        entry = cohort_periods.setdefault(period_idx, {"customers": set(), "revenue": Decimal("0.00")})
        entry["customers"].add(cid)
        entry["revenue"] += amt

    return activity_map, total_revenue


def get_customer_cohort_analysis(
    organization: Organization | int,
    *,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
    max_periods: int = 12,
) -> CohortAnalysisResult:
    """Analyze customer cohort retention and recurring revenue by acquisition month."""
    org_id = organization.pk if isinstance(organization, Organization) else organization

    invoice_qs = Invoice.all_tenants.filter(
        organization_id=org_id,
        status__in=[InvoiceStatus.POSTED, InvoiceStatus.PAID],
    ).exclude(customer=None)

    if start_date:
        invoice_qs = invoice_qs.filter(invoice_date__gte=start_date)
    if end_date:
        invoice_qs = invoice_qs.filter(invoice_date__lte=end_date)

    invoices = list(invoice_qs.values("customer_id", "invoice_date", "grand_total").order_by("invoice_date"))

    if not invoices:
        return CohortAnalysisResult(
            cohorts=[],
            total_customers=0,
            total_cohorts=0,
            avg_m1_retention=0.0,
            total_lifetime_revenue=Decimal("0.00"),
            periods_header=[],
        )

    customer_first_month = _group_customer_first_purchases(invoices)
    cohort_customers: dict[str, set[int]] = {}
    customer_cohort_key: dict[int, str] = {}
    for cid, first_d in customer_first_month.items():
        key = first_d.strftime("%Y-%m")
        cohort_customers.setdefault(key, set()).add(cid)
        customer_cohort_key[cid] = key

    sorted_cohort_keys = sorted(cohort_customers.keys())
    activity_map, total_revenue = _build_cohort_activity_map(
        invoices, customer_cohort_key, customer_first_month, max_periods
    )

    cohorts_list: list[CustomerCohort] = []
    max_observed_period = 0
    m1_rates: list[float] = []

    for ckey in sorted_cohort_keys:
        c_size = len(cohort_customers[ckey])
        cohort_rev = Decimal("0.00")
        periods_list: list[CohortPeriodData] = []
        cohort_activities = activity_map.get(ckey, {})
        observed_in_cohort = max(cohort_activities.keys(), default=0)
        max_observed_period = max(max_observed_period, min(observed_in_cohort, max_periods - 1))

        for p_idx in range(observed_in_cohort + 1):
            if p_idx >= max_periods:
                break
            p_data = cohort_activities.get(p_idx, {"customers": set(), "revenue": Decimal("0.00")})
            active_cnt = len(p_data["customers"])
            rev = p_data["revenue"]
            cohort_rev += rev
            rate = round((active_cnt / c_size * 100.0) if c_size > 0 else 0.0, 1)

            periods_list.append(
                CohortPeriodData(
                    period=p_idx,
                    active_customers=active_cnt,
                    retention_rate=rate,
                    revenue=rev,
                )
            )
            if p_idx == 1 and c_size > 0:
                m1_rates.append(rate)

        cohorts_list.append(
            CustomerCohort(
                cohort_month=ckey,
                cohort_size=c_size,
                total_cohort_revenue=cohort_rev,
                periods=periods_list,
            )
        )

    avg_m1 = round(sum(m1_rates) / len(m1_rates), 1) if m1_rates else 0.0
    return CohortAnalysisResult(
        cohorts=cohorts_list,
        total_customers=len(customer_first_month),
        total_cohorts=len(cohorts_list),
        avg_m1_retention=avg_m1,
        total_lifetime_revenue=total_revenue,
        periods_header=list(range(max_observed_period + 1)),
    )


# =============================================================================
# 2. Product ABC Pareto Analysis
# =============================================================================


@dataclass
class ProductAbcItem:
    product_id: int
    name: str
    sku: str
    category_name: str
    total_revenue: Decimal
    total_quantity: Decimal
    total_cost: Decimal
    gross_profit: Decimal
    margin_percentage: float
    cumulative_revenue: Decimal
    cumulative_percentage: float
    tier: str  # "A", "B", "C"

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "sku": self.sku,
            "category_name": self.category_name,
            "total_revenue": str(self.total_revenue),
            "total_quantity": str(self.total_quantity),
            "total_cost": str(self.total_cost),
            "gross_profit": str(self.gross_profit),
            "margin_percentage": self.margin_percentage,
            "cumulative_revenue": str(self.cumulative_revenue),
            "cumulative_percentage": self.cumulative_percentage,
            "tier": self.tier,
        }


@dataclass
class AbcTierSummary:
    tier: str  # "A", "B", "C"
    tier_label: str
    product_count: int
    product_share_pct: float
    total_revenue: Decimal
    revenue_share_pct: float

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_revenue"] = str(self.total_revenue)
        return d


@dataclass
class ProductAbcResult:
    items: list[ProductAbcItem]
    tier_summaries: list[AbcTierSummary]
    total_revenue: Decimal
    total_products_count: int
    active_revenue_products_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "tier_summaries": [ts.to_dict() for ts in self.tier_summaries],
            "total_revenue": str(self.total_revenue),
            "total_products_count": self.total_products_count,
            "active_revenue_products_count": self.active_revenue_products_count,
        }


def get_product_abc_analysis(
    organization: Organization | int,
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    warehouse_id: int | None = None,
) -> ProductAbcResult:
    """Classify products using Pareto ABC analysis based on revenue contribution."""
    org_id = organization.pk if isinstance(organization, Organization) else organization

    line_qs = InvoiceLine.all_tenants.filter(
        invoice__organization_id=org_id,
        invoice__status__in=[InvoiceStatus.POSTED, InvoiceStatus.PAID],
    )
    if date_from:
        line_qs = line_qs.filter(invoice__invoice_date__gte=date_from)
    if date_to:
        line_qs = line_qs.filter(invoice__invoice_date__lte=date_to)
    if warehouse_id:
        line_qs = line_qs.filter(invoice__warehouse_id=warehouse_id)

    aggregated = list(
        line_qs.values(
            "product_id",
            "product__name",
            "product__sku",
            "product__category__name",
        )
        .annotate(
            sum_revenue=Sum("line_total"),
            sum_quantity=Sum("quantity"),
            sum_cost=Sum(
                F("quantity") * Coalesce(F("unit_cost"), F("product__cost_price"), Decimal("0.0000"))
            ),
        )
        .order_by("-sum_revenue")
    )

    total_catalog_products = Product.all_tenants.filter(
        organization_id=org_id,
        is_active=True,
    ).count()

    overall_revenue = sum(
        (Decimal(str(row["sum_revenue"] or "0.00")) for row in aggregated),
        Decimal("0.00"),
    )

    if overall_revenue <= Decimal("0.00") or not aggregated:
        empty_summaries = [
            AbcTierSummary("A", _("Class A (Top 80% Revenue)"), 0, 0.0, Decimal("0.00"), 0.0),
            AbcTierSummary("B", _("Class B (Next 15% Revenue)"), 0, 0.0, Decimal("0.00"), 0.0),
            AbcTierSummary(
                "C", _("Class C (Bottom 5% Revenue)"), total_catalog_products, 100.0, Decimal("0.00"), 0.0
            ),
        ]
        return ProductAbcResult(
            items=[],
            tier_summaries=empty_summaries,
            total_revenue=Decimal("0.00"),
            total_products_count=total_catalog_products,
            active_revenue_products_count=0,
        )

    items: list[ProductAbcItem] = []
    cumulative_rev = Decimal("0.00")
    tier_counts = {"A": 0, "B": 0, "C": 0}
    tier_revenues = {"A": Decimal("0.00"), "B": Decimal("0.00"), "C": Decimal("0.00")}

    for row in aggregated:
        rev = Decimal(str(row["sum_revenue"] or "0.00"))
        qty = Decimal(str(row["sum_quantity"] or "0.0000"))
        cost = Decimal(str(row["sum_cost"] or "0.0000"))
        profit = rev - cost
        margin_pct = round(float(profit / rev * 100), 2) if rev > Decimal("0.00") else 0.0

        prev_cum_pct = float(cumulative_rev / overall_revenue * 100)
        cumulative_rev += rev
        current_cum_pct = min(100.0, round(float(cumulative_rev / overall_revenue * 100), 2))

        tier = "A" if prev_cum_pct < 80.0 else ("B" if prev_cum_pct < 95.0 else "C")
        tier_counts[tier] += 1
        tier_revenues[tier] += rev

        items.append(
            ProductAbcItem(
                product_id=row["product_id"],
                name=row["product__name"] or _("Unnamed Product"),
                sku=row["product__sku"] or "",
                category_name=row["product__category__name"] or _("Uncategorized"),
                total_revenue=rev,
                total_quantity=qty,
                total_cost=cost,
                gross_profit=profit,
                margin_percentage=margin_pct,
                cumulative_revenue=cumulative_rev,
                cumulative_percentage=current_cum_pct,
                tier=tier,
            )
        )

    zero_rev_count = max(0, total_catalog_products - len(items))
    tier_counts["C"] += zero_rev_count
    tot_count = len(items) + zero_rev_count

    summaries = [
        AbcTierSummary(
            tier="A",
            tier_label=_("Class A (Top ~80% Value)"),
            product_count=tier_counts["A"],
            product_share_pct=round(tier_counts["A"] / tot_count * 100.0, 1) if tot_count > 0 else 0.0,
            total_revenue=tier_revenues["A"],
            revenue_share_pct=round(float(tier_revenues["A"] / overall_revenue * 100), 1),
        ),
        AbcTierSummary(
            tier="B",
            tier_label=_("Class B (Next ~15% Value)"),
            product_count=tier_counts["B"],
            product_share_pct=round(tier_counts["B"] / tot_count * 100.0, 1) if tot_count > 0 else 0.0,
            total_revenue=tier_revenues["B"],
            revenue_share_pct=round(float(tier_revenues["B"] / overall_revenue * 100), 1),
        ),
        AbcTierSummary(
            tier="C",
            tier_label=_("Class C (Bottom ~5% Value)"),
            product_count=tier_counts["C"],
            product_share_pct=round(tier_counts["C"] / tot_count * 100.0, 1) if tot_count > 0 else 0.0,
            total_revenue=tier_revenues["C"],
            revenue_share_pct=round(float(tier_revenues["C"] / overall_revenue * 100), 1),
        ),
    ]

    return ProductAbcResult(
        items=items,
        tier_summaries=summaries,
        total_revenue=overall_revenue,
        total_products_count=tot_count,
        active_revenue_products_count=len(items),
    )


# =============================================================================
# 3. Profit & Margin Analysis
# =============================================================================


@dataclass
class ProductMarginItem:
    product_id: int
    name: str
    sku: str
    category_name: str
    units_sold: Decimal
    revenue: Decimal
    cost: Decimal
    gross_profit: Decimal
    margin_percentage: float
    margin_health: str  # "high", "healthy", "moderate", "low", "negative"

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "sku": self.sku,
            "category_name": self.category_name,
            "units_sold": str(self.units_sold),
            "revenue": str(self.revenue),
            "cost": str(self.cost),
            "gross_profit": str(self.gross_profit),
            "margin_percentage": self.margin_percentage,
            "margin_health": self.margin_health,
        }


@dataclass
class CategoryMarginItem:
    category_name: str
    product_count: int
    revenue: Decimal
    cost: Decimal
    gross_profit: Decimal
    margin_percentage: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "category_name": self.category_name,
            "product_count": self.product_count,
            "revenue": str(self.revenue),
            "cost": str(self.cost),
            "gross_profit": str(self.gross_profit),
            "margin_percentage": self.margin_percentage,
        }


@dataclass
class MarginAnalysisResult:
    products: list[ProductMarginItem]
    categories: list[CategoryMarginItem]
    total_revenue: Decimal
    total_cost: Decimal
    total_gross_profit: Decimal
    blended_margin_percentage: float
    top_profitable_products: list[ProductMarginItem]
    lowest_margin_products: list[ProductMarginItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "products": [p.to_dict() for p in self.products],
            "categories": [c.to_dict() for c in self.categories],
            "total_revenue": str(self.total_revenue),
            "total_cost": str(self.total_cost),
            "total_gross_profit": str(self.total_gross_profit),
            "blended_margin_percentage": self.blended_margin_percentage,
            "top_profitable_products": [p.to_dict() for p in self.top_profitable_products],
            "lowest_margin_products": [p.to_dict() for p in self.lowest_margin_products],
        }


def _classify_margin_health(margin_pct: float) -> str:
    """Classify margin percentage into visual health bands."""
    if margin_pct >= 50.0:
        return "high"
    if margin_pct >= 30.0:
        return "healthy"
    if margin_pct >= 15.0:
        return "moderate"
    if margin_pct >= 0.0:
        return "low"
    return "negative"


def get_margin_analysis(
    organization: Organization | int,
    *,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    branch_id: int | None = None,
    warehouse_id: int | None = None,
    category_id: int | None = None,
) -> MarginAnalysisResult:
    """Compute gross profit margins across products and product categories."""
    org_id = organization.pk if isinstance(organization, Organization) else organization

    qs = InvoiceLine.all_tenants.filter(
        invoice__organization_id=org_id,
        invoice__status__in=[InvoiceStatus.POSTED, InvoiceStatus.PAID],
    )
    if date_from:
        qs = qs.filter(invoice__invoice_date__gte=date_from)
    if date_to:
        qs = qs.filter(invoice__invoice_date__lte=date_to)
    if branch_id:
        qs = qs.filter(invoice__branch_id=branch_id)
    if warehouse_id:
        qs = qs.filter(invoice__warehouse_id=warehouse_id)
    if category_id:
        qs = qs.filter(product__category_id=category_id)

    aggregated = list(
        qs.values(
            "product_id",
            "product__name",
            "product__sku",
            "product__category__name",
        )
        .annotate(
            tot_revenue=Sum("line_total"),
            tot_qty=Sum("quantity"),
            tot_cost=Sum(
                F("quantity") * Coalesce(F("unit_cost"), F("product__cost_price"), Decimal("0.0000"))
            ),
        )
        .order_by("-tot_revenue")
    )

    product_items: list[ProductMarginItem] = []
    category_map: dict[str, dict[str, Any]] = {}
    total_revenue = Decimal("0.00")
    total_cost = Decimal("0.00")

    for row in aggregated:
        rev = Decimal(str(row["tot_revenue"] or "0.00"))
        cost = Decimal(str(row["tot_cost"] or "0.00"))
        qty = Decimal(str(row["tot_qty"] or "0.0000"))
        profit = rev - cost
        margin_pct = round(float(profit / rev * 100), 2) if rev > Decimal("0.00") else 0.0

        total_revenue += rev
        total_cost += cost
        health = _classify_margin_health(margin_pct)

        cat_name = row["product__category__name"] or _("Uncategorized")
        entry = category_map.setdefault(
            cat_name,
            {"product_ids": set(), "revenue": Decimal("0.00"), "cost": Decimal("0.00")},
        )
        entry["product_ids"].add(row["product_id"])
        entry["revenue"] += rev
        entry["cost"] += cost

        product_items.append(
            ProductMarginItem(
                product_id=row["product_id"],
                name=row["product__name"] or _("Unnamed Product"),
                sku=row["product__sku"] or "",
                category_name=cat_name,
                units_sold=qty,
                revenue=rev,
                cost=cost,
                gross_profit=profit,
                margin_percentage=margin_pct,
                margin_health=health,
            )
        )

    category_items = [
        CategoryMarginItem(
            category_name=cname,
            product_count=len(cdata["product_ids"]),
            revenue=cdata["revenue"],
            cost=cdata["cost"],
            gross_profit=cdata["revenue"] - cdata["cost"],
            margin_percentage=(
                round(float((cdata["revenue"] - cdata["cost"]) / cdata["revenue"] * 100), 2)
                if cdata["revenue"] > Decimal("0.00")
                else 0.0
            ),
        )
        for cname, cdata in category_map.items()
    ]
    category_items.sort(key=lambda c: -c.revenue)

    total_gross_profit = total_revenue - total_cost
    blended_margin = (
        round(float(total_gross_profit / total_revenue * 100), 2) if total_revenue > Decimal("0.00") else 0.0
    )

    top_profitable = sorted(product_items, key=lambda p: -p.gross_profit)[:5]
    lowest_margin = sorted(product_items, key=lambda p: (p.margin_percentage, p.gross_profit))[:5]

    return MarginAnalysisResult(
        products=product_items,
        categories=category_items,
        total_revenue=total_revenue,
        total_cost=total_cost,
        total_gross_profit=total_gross_profit,
        blended_margin_percentage=blended_margin,
        top_profitable_products=top_profitable,
        lowest_margin_products=lowest_margin,
    )


# =============================================================================
# 4. Reorder Demand Forecasting (Moving Average)
# =============================================================================


@dataclass
class DemandForecastItem:
    product_id: int
    name: str
    sku: str
    category_name: str
    on_hand: Decimal
    reorder_point: Decimal
    units_sold_in_window: Decimal
    daily_run_rate: float  # Units/day
    days_of_inventory: int  # Projected days remaining
    lead_time_days: int
    projected_stockout_date: str | None
    urgency: str  # "stockout", "urgent", "soon", "adequate", "surplus"
    suggested_reorder_qty: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "name": self.name,
            "sku": self.sku,
            "category_name": self.category_name,
            "on_hand": str(self.on_hand),
            "reorder_point": str(self.reorder_point),
            "units_sold_in_window": str(self.units_sold_in_window),
            "daily_run_rate": self.daily_run_rate,
            "days_of_inventory": self.days_of_inventory,
            "lead_time_days": self.lead_time_days,
            "projected_stockout_date": self.projected_stockout_date,
            "urgency": self.urgency,
            "suggested_reorder_qty": str(self.suggested_reorder_qty),
        }


@dataclass
class DemandForecastResult:
    items: list[DemandForecastItem]
    window_days: int
    critical_reorders_count: int
    soon_reorders_count: int
    total_monitored_products: int
    fastest_moving_products: list[DemandForecastItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [it.to_dict() for it in self.items],
            "window_days": self.window_days,
            "critical_reorders_count": self.critical_reorders_count,
            "soon_reorders_count": self.soon_reorders_count,
            "total_monitored_products": self.total_monitored_products,
            "fastest_moving_products": [it.to_dict() for it in self.fastest_moving_products],
        }


def _calculate_forecast_urgency_and_qty(
    on_hand: Decimal,
    daily_rate: float,
    *,
    lead_time_days: int,
    reorder_point: Decimal,
    reorder_batch: Decimal,
    today: datetime.date,
) -> tuple[str, int, str | None, Decimal]:
    """Calculate depletion status, days remaining, stockout date, and suggested reorder qty."""
    if on_hand <= Decimal("0.0000"):
        days_remaining = 0
        urgency = "stockout"
        stockout_date_str = today.strftime("%Y-%m-%d")
    elif daily_rate > 0.0001:
        days_remaining = int(float(on_hand) / daily_rate)
        stockout_date_str = (today + datetime.timedelta(days=days_remaining)).strftime("%Y-%m-%d")

        if days_remaining <= lead_time_days:
            urgency = "urgent"
        elif days_remaining <= (lead_time_days + 7):
            urgency = "soon"
        elif days_remaining <= 60:
            urgency = "adequate"
        else:
            urgency = "surplus"
    else:
        days_remaining = 999
        urgency = "adequate" if on_hand > 0 else "stockout"
        stockout_date_str = None

    if urgency in ("stockout", "urgent", "soon"):
        monthly_target = Decimal(str(round(daily_rate * 30, 2)))
        safety_target = reorder_point * Decimal("2.0")
        target_stock = max(reorder_batch, monthly_target, safety_target)
        suggested_qty = max(Decimal("1.0000"), target_stock - on_hand)
        suggested_qty = Decimal(str(int(suggested_qty.to_integral_value())))
    else:
        suggested_qty = Decimal("0.0000")

    return urgency, days_remaining, stockout_date_str, suggested_qty


def get_reorder_demand_forecast(
    organization: Organization | int,
    *,
    window_days: int = 30,
    lead_time_days: int = 14,
    warehouse_id: int | None = None,
) -> DemandForecastResult:
    """Project inventory depletion and calculate recommended reorder quantities using Moving Average."""
    org_id = organization.pk if isinstance(organization, Organization) else organization
    today = timezone.now().date()
    window_start = today - datetime.timedelta(days=window_days)

    products = list(
        Product.all_tenants.filter(
            organization_id=org_id,
            type=ProductType.STOCK,
            is_active=True,
        ).select_related("category")
    )

    if not products:
        return DemandForecastResult(
            items=[],
            window_days=window_days,
            critical_reorders_count=0,
            soon_reorders_count=0,
            total_monitored_products=0,
            fastest_moving_products=[],
        )

    sales_qs = InvoiceLine.all_tenants.filter(
        invoice__organization_id=org_id,
        invoice__status__in=[InvoiceStatus.POSTED, InvoiceStatus.PAID],
        invoice__invoice_date__gte=window_start,
        invoice__invoice_date__lte=today,
    )
    if warehouse_id:
        sales_qs = sales_qs.filter(invoice__warehouse_id=warehouse_id)

    sales_by_product = {
        row["product_id"]: Decimal(str(row["qty"] or "0.0000"))
        for row in sales_qs.values("product_id").annotate(qty=Sum("quantity"))
    }

    stock_qs = StockLevel.all_tenants.filter(organization_id=org_id)
    if warehouse_id:
        stock_qs = stock_qs.filter(warehouse_id=warehouse_id)

    stock_by_product: dict[int, dict[str, Decimal]] = {}
    for row in stock_qs.values("product_id").annotate(
        tot_on_hand=Sum("on_hand"),
        max_reorder_point=Sum("reorder_point"),
    ):
        stock_by_product[row["product_id"]] = {
            "on_hand": Decimal(str(row["tot_on_hand"] or "0.0000")),
            "reorder_point": Decimal(str(row["max_reorder_point"] or "0.0000")),
        }

    items: list[DemandForecastItem] = []
    critical_count = 0
    soon_count = 0

    for prod in products:
        pid = prod.pk
        sold_qty = sales_by_product.get(pid, Decimal("0.0000"))
        daily_rate = float(sold_qty / window_days) if window_days > 0 else 0.0

        default_stk = {"on_hand": Decimal("0.0000"), "reorder_point": Decimal("0.0000")}
        stk_info = stock_by_product.get(pid, default_stk)
        on_hand = stk_info["on_hand"]
        reorder_point = (
            stk_info["reorder_point"]
            if stk_info["reorder_point"] > Decimal("0.0000")
            else (prod.reorder_level or Decimal("0.0000"))
        )
        reorder_batch = prod.reorder_quantity or Decimal("0.0000")

        urgency, days_rem, stockout_str, suggested_qty = _calculate_forecast_urgency_and_qty(
            on_hand,
            daily_rate,
            lead_time_days=lead_time_days,
            reorder_point=reorder_point,
            reorder_batch=reorder_batch,
            today=today,
        )
        if urgency in ("stockout", "urgent"):
            critical_count += 1
        elif urgency == "soon":
            soon_count += 1

        cat_name = prod.category.name if prod.category else _("Uncategorized")
        items.append(
            DemandForecastItem(
                product_id=pid,
                name=prod.name,
                sku=prod.sku,
                category_name=cat_name,
                on_hand=on_hand,
                reorder_point=reorder_point,
                units_sold_in_window=sold_qty,
                daily_run_rate=round(daily_rate, 2),
                days_of_inventory=days_rem,
                lead_time_days=lead_time_days,
                projected_stockout_date=stockout_str,
                urgency=urgency,
                suggested_reorder_qty=suggested_qty,
            )
        )

    urgency_prio = {"stockout": 0, "urgent": 1, "soon": 2, "adequate": 3, "surplus": 4}
    items.sort(key=lambda x: (urgency_prio.get(x.urgency, 5), x.days_of_inventory, -x.daily_run_rate))
    fastest_moving = sorted(items, key=lambda x: -x.daily_run_rate)[:5]

    return DemandForecastResult(
        items=items,
        window_days=window_days,
        critical_reorders_count=critical_count,
        soon_reorders_count=soon_count,
        total_monitored_products=len(items),
        fastest_moving_products=fastest_moving,
    )
