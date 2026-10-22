"""Read-only selectors for Point of Sale (POS) operations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import DecimalField, F, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce

from apps.catalog.models import Category, Product
from apps.inventory.models import StockLevel
from apps.pos.models import (
    POSHeldCart,
    POSRegister,
    POSSale,
    POSShift,
    POSShiftStatus,
)
from apps.tenancy.models import Organization, Warehouse


def list_registers(
    *,
    organization: Organization,
    branch_id: int | None = None,
    is_active: bool | None = None,
) -> QuerySet[POSRegister]:
    """List POS registers scoped by tenant organization."""
    qs = POSRegister.all_tenants.filter(organization=organization).select_related("branch", "warehouse")
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return qs.order_by("code")


def get_register(
    *,
    organization: Organization,
    register_id: int | None = None,
    public_id: str | None = None,
) -> POSRegister | None:
    """Fetch single POS register by primary key or public_id."""
    qs = POSRegister.all_tenants.filter(organization=organization).select_related("branch", "warehouse")
    if register_id:
        return qs.filter(pk=register_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def get_open_shift_for_register(
    *,
    organization: Organization,
    register: POSRegister,
) -> POSShift | None:
    """Get the currently open shift on a register if any."""
    return (
        POSShift.all_tenants.filter(
            organization=organization,
            register=register,
            status=POSShiftStatus.OPEN,
        )
        .select_related("register", "cashier")
        .first()
    )


def get_active_shift_for_user(
    *,
    organization: Organization,
    user: Any,
) -> POSShift | None:
    """Get the cashier's active open shift if any."""
    return (
        POSShift.all_tenants.filter(
            organization=organization,
            cashier=user,
            status=POSShiftStatus.OPEN,
        )
        .select_related("register", "cashier")
        .first()
    )


def list_shifts(
    *,
    organization: Organization,
    register_id: int | None = None,
    cashier_id: int | None = None,
    status: str | None = None,
) -> QuerySet[POSShift]:
    """List cashier shifts with filters."""
    qs = POSShift.all_tenants.filter(organization=organization).select_related("register", "cashier")
    if register_id:
        qs = qs.filter(register_id=register_id)
    if cashier_id:
        qs = qs.filter(cashier_id=cashier_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-opened_at")


def get_shift(
    *,
    organization: Organization,
    shift_id: int | None = None,
    public_id: str | None = None,
) -> POSShift | None:
    """Fetch a single POS shift."""
    qs = POSShift.all_tenants.filter(organization=organization).select_related(
        "register", "cashier", "variance_journal_entry"
    )
    if shift_id:
        return qs.filter(pk=shift_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_sales(
    *,
    organization: Organization,
    shift_id: int | None = None,
    register_id: int | None = None,
    search: str | None = None,
) -> QuerySet[POSSale]:
    """List completed POS sales."""
    qs = POSSale.all_tenants.filter(organization=organization).select_related(
        "shift", "register", "cashier", "customer", "invoice"
    )
    if shift_id:
        qs = qs.filter(shift_id=shift_id)
    if register_id:
        qs = qs.filter(register_id=register_id)
    if search:
        qs = qs.filter(
            Q(receipt_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(invoice__invoice_number__icontains=search)
        )
    return qs.order_by("-created_at")


def get_sale(
    *,
    organization: Organization,
    sale_id: int | None = None,
    public_id: str | None = None,
) -> POSSale | None:
    """Fetch a single completed POS sale with invoice and line items."""
    qs = POSSale.all_tenants.filter(organization=organization).select_related(
        "shift", "register", "cashier", "customer", "invoice"
    )
    if sale_id:
        return qs.filter(pk=sale_id).first()
    if public_id:
        return qs.filter(public_id=public_id).first()
    return None


def list_held_carts(
    *,
    organization: Organization,
    shift_id: int,
) -> QuerySet[POSHeldCart]:
    """List parked/held carts for a given shift."""
    return (
        POSHeldCart.all_tenants.filter(
            organization=organization,
            shift_id=shift_id,
        )
        .select_related("customer")
        .order_by("-created_at")
    )


def get_pos_catalog_products(
    *,
    organization: Organization,
    search: str | None = None,
    category_id: int | None = None,
    warehouse: Warehouse | None = None,
) -> QuerySet[Product]:
    """Fetch active products for the POS touch grid and barcode lookup, with warehouse stock levels."""
    qs = Product.all_tenants.filter(
        organization=organization,
        is_active=True,
    ).select_related("category", "unit", "tax_code")

    if warehouse:
        stock_subquery = (
            StockLevel.all_tenants.filter(
                organization=organization,
                product=OuterRef("pk"),
                warehouse=warehouse,
            )
            .annotate(avail=F("on_hand") - F("reserved"))
            .values("avail")[:1]
        )
        qs = qs.annotate(
            stock_qty=Coalesce(
                Subquery(stock_subquery),
                Value(Decimal("0.0000")),
                output_field=DecimalField(max_digits=18, decimal_places=4),
            )
        )

    if category_id:
        qs = qs.filter(category_id=category_id)
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(sku__icontains=search) | Q(barcode__icontains=search))
    return qs.order_by("name")[:100]


def get_pos_categories(
    *,
    organization: Organization,
) -> QuerySet[Category]:
    """Fetch active categories for POS quick filter buttons."""
    return Category.all_tenants.filter(
        organization=organization,
        is_active=True,
    ).order_by("name")
