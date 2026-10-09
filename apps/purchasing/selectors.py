"""Selectors and read queries for the Purchasing module (optimized, no N+1)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import QuerySet, Sum

from apps.purchasing.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseOrderStatus,
    PurchaseReturn,
    Supplier,
    SupplierBill,
    SupplierBillStatus,
    SupplierPayment,
)
from apps.tenancy.models import Organization


def list_suppliers(
    *,
    organization: Organization,
    is_active: bool | None = None,
    search: str | None = None,
) -> QuerySet[Supplier]:
    """List suppliers with optional active and text search filters."""
    qs = Supplier.all_tenants.filter(organization=organization)
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    if search:
        qs = qs.filter(name__icontains=search) | qs.filter(code__icontains=search)
    return qs.order_by("name")


def get_supplier(
    *,
    organization: Organization,
    supplier_id: int | str,
) -> Supplier | None:
    """Get single supplier by integer PK or public UUID."""
    if isinstance(supplier_id, int) or (isinstance(supplier_id, str) and supplier_id.isdigit()):
        return Supplier.all_tenants.filter(organization=organization, pk=int(supplier_id)).first()
    return Supplier.all_tenants.filter(organization=organization, public_id=supplier_id).first()


def list_purchase_orders(
    *,
    organization: Organization,
    supplier_id: int | None = None,
    status: str | None = None,
) -> QuerySet[PurchaseOrder]:
    """List purchase orders with related supplier, warehouse, and branch."""
    qs = (
        PurchaseOrder.all_tenants.filter(organization=organization)
        .select_related("supplier", "branch", "warehouse", "approved_by")
        .prefetch_related("lines__product")
    )
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-order_date", "-id")


def get_purchase_order(
    *,
    organization: Organization,
    order_id: int | str,
) -> PurchaseOrder | None:
    """Get single purchase order with preloaded relations."""
    qs = (
        PurchaseOrder.all_tenants.filter(organization=organization)
        .select_related("supplier", "branch", "warehouse", "approved_by")
        .prefetch_related("lines__product")
    )
    if isinstance(order_id, int) or (isinstance(order_id, str) and order_id.isdigit()):
        return qs.filter(pk=int(order_id)).first()
    return qs.filter(public_id=order_id).first()


def list_goods_receipts(
    *,
    organization: Organization,
    supplier_id: int | None = None,
    warehouse_id: int | None = None,
) -> QuerySet[GoodsReceipt]:
    """List goods receipts with supplier and warehouse preloaded."""
    qs = (
        GoodsReceipt.all_tenants.filter(organization=organization)
        .select_related("supplier", "warehouse", "purchase_order")
        .prefetch_related("lines__product")
    )
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    return qs.order_by("-date", "-id")


def get_goods_receipt(
    *,
    organization: Organization,
    receipt_id: int | str,
) -> GoodsReceipt | None:
    """Get single goods receipt with lines preloaded."""
    qs = (
        GoodsReceipt.all_tenants.filter(organization=organization)
        .select_related("supplier", "warehouse", "purchase_order")
        .prefetch_related("lines__product")
    )
    if isinstance(receipt_id, int) or (isinstance(receipt_id, str) and receipt_id.isdigit()):
        return qs.filter(pk=int(receipt_id)).first()
    return qs.filter(public_id=receipt_id).first()


def list_supplier_bills(
    *,
    organization: Organization,
    supplier_id: int | None = None,
    status: str | None = None,
) -> QuerySet[SupplierBill]:
    """List supplier bills with supplier and allocations preloaded."""
    qs = (
        SupplierBill.all_tenants.filter(organization=organization)
        .select_related("supplier", "purchase_order", "goods_receipt", "journal_entry")
        .prefetch_related("lines__product", "allocations__payment")
    )
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-issue_date", "-id")


def get_supplier_bill(
    *,
    organization: Organization,
    bill_id: int | str,
) -> SupplierBill | None:
    """Get single supplier bill with line items and allocations."""
    qs = (
        SupplierBill.all_tenants.filter(organization=organization)
        .select_related("supplier", "purchase_order", "goods_receipt", "journal_entry")
        .prefetch_related("lines__product", "allocations__payment")
    )
    if isinstance(bill_id, int) or (isinstance(bill_id, str) and bill_id.isdigit()):
        return qs.filter(pk=int(bill_id)).first()
    return qs.filter(public_id=bill_id).first()


def list_supplier_payments(
    *,
    organization: Organization,
    supplier_id: int | None = None,
) -> QuerySet[SupplierPayment]:
    """List supplier payments with supplier and allocations."""
    qs = (
        SupplierPayment.all_tenants.filter(organization=organization)
        .select_related("supplier", "journal_entry")
        .prefetch_related("allocations__bill")
    )
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    return qs.order_by("-payment_date", "-id")


def get_supplier_payment(
    *,
    organization: Organization,
    payment_id: int | str,
) -> SupplierPayment | None:
    """Get single supplier payment."""
    qs = (
        SupplierPayment.all_tenants.filter(organization=organization)
        .select_related("supplier", "journal_entry")
        .prefetch_related("allocations__bill")
    )
    if isinstance(payment_id, int) or (isinstance(payment_id, str) and payment_id.isdigit()):
        return qs.filter(pk=int(payment_id)).first()
    return qs.filter(public_id=payment_id).first()


def list_purchase_returns(
    *,
    organization: Organization,
    supplier_id: int | None = None,
) -> QuerySet[PurchaseReturn]:
    """List purchase returns."""
    qs = (
        PurchaseReturn.all_tenants.filter(organization=organization)
        .select_related("supplier", "warehouse", "goods_receipt", "bill", "journal_entry")
        .prefetch_related("lines__product")
    )
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    return qs.order_by("-return_date", "-id")


def get_purchase_return(
    *,
    organization: Organization,
    return_id: int | str,
) -> PurchaseReturn | None:
    """Get single purchase return."""
    qs = (
        PurchaseReturn.all_tenants.filter(organization=organization)
        .select_related("supplier", "warehouse", "goods_receipt", "bill", "journal_entry")
        .prefetch_related("lines__product")
    )
    if isinstance(return_id, int) or (isinstance(return_id, str) and return_id.isdigit()):
        return qs.filter(pk=int(return_id)).first()
    return qs.filter(public_id=return_id).first()


def get_purchasing_summary(
    *,
    organization: Organization,
) -> dict[str, Any]:
    """Aggregate dashboard metrics for purchasing."""
    total_ap = Supplier.all_tenants.filter(organization=organization).aggregate(total=Sum("current_balance"))[
        "total"
    ] or Decimal("0.0000")
    pending_bills_total = SupplierBill.all_tenants.filter(
        organization=organization,
        status__in=[SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID],
    ).aggregate(due=Sum("balance_due"))["due"] or Decimal("0.0000")
    active_pos_count = PurchaseOrder.all_tenants.filter(
        organization=organization,
        status__in=[PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.APPROVED],
    ).count()

    return {
        "total_ap_balance": total_ap,
        "pending_bills_due": pending_bills_total,
        "active_pos_count": active_pos_count,
    }
