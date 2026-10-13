"""Domain write services for Purchasing.
Suppliers, Purchase Orders, Goods Receipts, Bills, Payments, Returns.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting import services as accounting_services
from apps.catalog.models import Product
from apps.core import events
from apps.core.services import generate_next_number
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory_services
from apps.purchasing.events import (
    GoodsReceiptCreated,
    PurchaseOrderApproved,
    PurchaseOrderCreated,
    PurchaseReturnPosted,
    SupplierBillCreated,
    SupplierBillPosted,
    SupplierCreated,
    SupplierPaymentRecorded,
    SupplierUpdated,
)
from apps.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseReturn,
    PurchaseReturnLine,
    PurchaseReturnStatus,
    Supplier,
    SupplierBill,
    SupplierBillLine,
    SupplierBillStatus,
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierPaymentMethod,
)
from apps.tenancy.models import Branch, Organization, Warehouse

FOUR_PLACES = Decimal("0.0001")


def _quantize_money(val: Decimal | str | float) -> Decimal:
    return Decimal(str(val)).quantize(FOUR_PLACES)


# =============================================================================
# 1. Supplier Services
# =============================================================================


@transaction.atomic
def create_supplier(
    *,
    organization: Organization,
    name: str,
    code: str | None = None,
    contact_person: str = "",
    email: str = "",
    phone: str = "",
    address: str = "",
    city: str = "",
    country: str = "",
    postal_code: str = "",
    tax_id: str = "",
    currency: str = "USD",
    payment_terms_days: int = 30,
    notes: str = "",
    actor: Any,
) -> Supplier:
    """Create a new vendor/supplier within an organization."""
    if not code:
        code = generate_next_number(
            organization_id=organization.pk,
            name="supplier_code",
            prefix="SUP-",
            padding=4,
            actor=actor,
        )

    if Supplier.all_tenants.filter(organization=organization, code=code).exists():
        raise ValidationError(_("Supplier with code '%(code)s' already exists.") % {"code": code})

    supplier = Supplier.all_tenants.create(
        organization=organization,
        code=code,
        name=name,
        contact_person=contact_person,
        email=email,
        phone=phone,
        address=address,
        city=city,
        country=country,
        postal_code=postal_code,
        tax_id=tax_id,
        currency=currency,
        payment_terms_days=payment_terms_days,
        current_balance=Decimal("0.0000"),
        is_active=True,
        notes=notes,
        created_by=actor,
    )

    events.publish(
        SupplierCreated(
            organization_id=organization.pk,
            supplier_id=supplier.pk,
            supplier_code=supplier.code,
        )
    )
    return supplier


@transaction.atomic
def update_supplier(
    *,
    organization: Organization,
    supplier: Supplier,
    name: str | None = None,
    contact_person: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    city: str | None = None,
    country: str | None = None,
    postal_code: str | None = None,
    tax_id: str | None = None,
    payment_terms_days: int | None = None,
    is_active: bool | None = None,
    notes: str | None = None,
    actor: Any,
) -> Supplier:
    """Update supplier contact and master data."""
    supp = Supplier.all_tenants.select_for_update().get(pk=supplier.pk, organization=organization)
    update_fields = ["updated_at"]

    if name is not None:
        supp.name = name
        update_fields.append("name")
    if contact_person is not None:
        supp.contact_person = contact_person
        update_fields.append("contact_person")
    if email is not None:
        supp.email = email
        update_fields.append("email")
    if phone is not None:
        supp.phone = phone
        update_fields.append("phone")
    if address is not None:
        supp.address = address
        update_fields.append("address")
    if city is not None:
        supp.city = city
        update_fields.append("city")
    if country is not None:
        supp.country = country
        update_fields.append("country")
    if postal_code is not None:
        supp.postal_code = postal_code
        update_fields.append("postal_code")
    if tax_id is not None:
        supp.tax_id = tax_id
        update_fields.append("tax_id")
    if payment_terms_days is not None:
        supp.payment_terms_days = payment_terms_days
        update_fields.append("payment_terms_days")
    if is_active is not None:
        supp.is_active = is_active
        update_fields.append("is_active")
    if notes is not None:
        supp.notes = notes
        update_fields.append("notes")

    supp.save(update_fields=update_fields)

    events.publish(
        SupplierUpdated(
            organization_id=organization.pk,
            supplier_id=supp.pk,
            supplier_code=supp.code,
        )
    )
    return supp


# =============================================================================
# 2. Purchase Order Services
# =============================================================================


@transaction.atomic
def create_purchase_order(
    *,
    organization: Organization,
    supplier: Supplier,
    branch: Branch | None = None,
    warehouse: Warehouse | None = None,
    order_date: datetime.date | None = None,
    expected_date: datetime.date | None = None,
    currency: str = "USD",
    exchange_rate: Decimal | str | float = "1.000000",
    lines: list[dict[str, Any]],
    notes: str = "",
    terms: str = "",
    actor: Any,
) -> PurchaseOrder:
    if supplier.organization_id != organization.pk:
        raise ValidationError(_("Supplier does not belong to organization."))
    if warehouse and warehouse.organization_id != organization.pk:
        raise ValidationError(_("Warehouse does not belong to organization."))
    if not lines:
        raise ValidationError(_("A purchase order requires at least one line item."))

    order_num = generate_next_number(
        organization_id=organization.pk,
        name="purchase_order",
        prefix="PO-",
        padding=5,
        actor=actor,
    )

    po = PurchaseOrder.all_tenants.create(
        organization=organization,
        order_number=order_num,
        supplier=supplier,
        branch=branch,
        warehouse=warehouse,
        order_date=order_date or timezone.now().date(),
        expected_date=expected_date,
        currency=currency,
        exchange_rate=_quantize_money(exchange_rate),
        status=PurchaseOrderStatus.DRAFT,
        notes=notes,
        terms=terms,
        created_by=actor,
    )

    subtotal_acc = Decimal("0.0000")
    tax_acc = Decimal("0.0000")

    for item in lines:
        product: Product = item["product"]
        qty = _quantize_money(item["quantity"])
        unit_price = _quantize_money(item["unit_price"])
        tax_rate = Decimal(str(item.get("tax_rate", "0.00")))

        if qty <= Decimal("0.0000"):
            raise ValidationError(_("Line item quantity must be strictly positive."))

        line_subtotal = _quantize_money(qty * unit_price)
        line_tax = _quantize_money(line_subtotal * (tax_rate / Decimal("100.00")))
        line_total = line_subtotal + line_tax

        PurchaseOrderLine.all_tenants.create(
            organization=organization,
            purchase_order=po,
            product=product,
            quantity=qty,
            received_quantity=Decimal("0.0000"),
            unit_price=unit_price,
            tax_rate=tax_rate,
            subtotal=line_subtotal,
            tax_amount=line_tax,
            total_amount=line_total,
            notes=item.get("notes", ""),
            created_by=actor,
        )

        subtotal_acc += line_subtotal
        tax_acc += line_tax

    po.subtotal = subtotal_acc
    po.tax_total = tax_acc
    po.grand_total = subtotal_acc + tax_acc
    po.save(update_fields=["subtotal", "tax_total", "grand_total", "updated_at"])

    events.publish(
        PurchaseOrderCreated(
            organization_id=organization.pk,
            order_id=po.pk,
            order_number=po.order_number,
        )
    )
    return po


@transaction.atomic
def submit_purchase_order(
    *,
    organization: Organization,
    purchase_order: PurchaseOrder,
    actor: Any,
) -> PurchaseOrder:
    """Submit a draft purchase order for approval or supplier transmission."""
    po = PurchaseOrder.all_tenants.select_for_update().get(pk=purchase_order.pk, organization=organization)
    if po.status != PurchaseOrderStatus.DRAFT:
        raise ValidationError(_("Only draft purchase orders can be submitted."))

    po.status = PurchaseOrderStatus.SUBMITTED
    po.save(update_fields=["status", "updated_at"])
    return po


@transaction.atomic
def approve_purchase_order(
    *,
    organization: Organization,
    purchase_order: PurchaseOrder,
    actor: Any,
) -> PurchaseOrder:
    """Approve a purchase order."""
    po = PurchaseOrder.all_tenants.select_for_update().get(pk=purchase_order.pk, organization=organization)
    if po.status not in (PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.SUBMITTED):
        raise ValidationError(_("Only draft or submitted purchase orders can be approved."))

    po.status = PurchaseOrderStatus.APPROVED
    po.approved_by = actor
    po.approved_at = timezone.now()
    po.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    events.publish(
        PurchaseOrderApproved(
            organization_id=organization.pk,
            order_id=po.pk,
            order_number=po.order_number,
        )
    )
    return po


@transaction.atomic
def cancel_purchase_order(
    *,
    organization: Organization,
    purchase_order: PurchaseOrder,
    actor: Any,
) -> PurchaseOrder:
    """Cancel a purchase order."""
    po = PurchaseOrder.all_tenants.select_for_update().get(pk=purchase_order.pk, organization=organization)
    if po.status == PurchaseOrderStatus.RECEIVED:
        raise ValidationError(_("Cannot cancel an already received purchase order."))

    po.status = PurchaseOrderStatus.CANCELLED
    po.save(update_fields=["status", "updated_at"])
    return po


# =============================================================================
# 3. Goods Receipt Services
# =============================================================================


@transaction.atomic
def create_goods_receipt(
    *,
    organization: Organization,
    supplier: Supplier,
    warehouse: Warehouse,
    purchase_order: PurchaseOrder | None = None,
    date: datetime.date | None = None,
    lines: list[dict[str, Any]],
    notes: str = "",
    actor: Any,
) -> GoodsReceipt:
    """Create a draft Goods Receipt."""
    if supplier.organization_id != organization.pk:
        raise ValidationError(_("Supplier does not belong to organization."))
    if warehouse.organization_id != organization.pk:
        raise ValidationError(_("Warehouse does not belong to organization."))
    if not lines:
        raise ValidationError(_("A goods receipt requires at least one received item line."))

    receipt_num = generate_next_number(
        organization_id=organization.pk,
        name="goods_receipt",
        prefix="GRN-",
        padding=5,
        actor=actor,
    )

    receipt = GoodsReceipt.all_tenants.create(
        organization=organization,
        receipt_number=receipt_num,
        purchase_order=purchase_order,
        supplier=supplier,
        warehouse=warehouse,
        date=date or timezone.now().date(),
        status=GoodsReceiptStatus.DRAFT,
        notes=notes,
        created_by=actor,
    )

    total_cost_acc = Decimal("0.0000")

    for item in lines:
        product: Product = item["product"]
        qty = _quantize_money(item["quantity"])
        unit_cost = _quantize_money(item["unit_cost"])
        po_line: PurchaseOrderLine | None = item.get("po_line")

        if qty <= Decimal("0.0000"):
            raise ValidationError(_("Received quantity must be strictly positive."))

        line_cost = _quantize_money(qty * unit_cost)

        GoodsReceiptLine.all_tenants.create(
            organization=organization,
            goods_receipt=receipt,
            po_line=po_line,
            product=product,
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=line_cost,
            created_by=actor,
        )
        total_cost_acc += line_cost

    receipt.total_cost = total_cost_acc
    receipt.save(update_fields=["total_cost", "updated_at"])

    events.publish(
        GoodsReceiptCreated(
            organization_id=organization.pk,
            receipt_id=receipt.pk,
            receipt_number=receipt.receipt_number,
        )
    )
    return receipt


@transaction.atomic
def receive_goods_receipt(
    *,
    organization: Organization,
    goods_receipt: GoodsReceipt,
    actor: Any,
) -> GoodsReceipt:
    """Confirm goods receipt: issues stock into warehouse at unit cost and updates PO lines."""
    receipt = GoodsReceipt.all_tenants.select_for_update().get(pk=goods_receipt.pk, organization=organization)
    if receipt.status != GoodsReceiptStatus.DRAFT:
        raise ValidationError(_("Only draft goods receipts can be confirmed into inventory."))

    lines = list(GoodsReceiptLine.all_tenants.filter(organization=organization, goods_receipt=receipt))

    # Move stock into warehouse via inventory services
    for line in lines:
        inventory_services.receive_stock(
            organization=organization,
            warehouse=receipt.warehouse,
            product=line.product,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
            reference_type="goods_receipt",
            reference_id=receipt.receipt_number,
            notes=f"Goods Receipt {receipt.receipt_number} from {receipt.supplier.name}",
            actor=actor,
        )

        if line.po_line:
            po_l = PurchaseOrderLine.all_tenants.select_for_update().get(pk=line.po_line.pk)
            po_l.received_quantity += line.quantity
            po_l.save(update_fields=["received_quantity", "updated_at"])

    # If linked to a PO, check if all lines received
    if receipt.purchase_order:
        po = PurchaseOrder.all_tenants.select_for_update().get(pk=receipt.purchase_order.pk)
        all_lines = list(po.lines.all())
        if all_lines and all(line_item.received_quantity >= line_item.quantity for line_item in all_lines):
            po.status = PurchaseOrderStatus.RECEIVED
            po.save(update_fields=["status", "updated_at"])

    receipt.status = GoodsReceiptStatus.RECEIVED
    receipt.save(update_fields=["status", "updated_at"])
    return receipt


# =============================================================================
# 4. Supplier Bill Services
# =============================================================================


@transaction.atomic
def create_supplier_bill(
    *,
    organization: Organization,
    supplier: Supplier,
    due_date: datetime.date,
    issue_date: datetime.date | None = None,
    supplier_reference: str = "",
    purchase_order: PurchaseOrder | None = None,
    goods_receipt: GoodsReceipt | None = None,
    currency: str = "USD",
    lines: list[dict[str, Any]],
    notes: str = "",
    actor: Any,
) -> SupplierBill:
    """Create a draft Supplier Bill."""
    if supplier.organization_id != organization.pk:
        raise ValidationError(_("Supplier does not belong to organization."))
    if not lines:
        raise ValidationError(_("A bill requires at least one line item."))

    bill_num = generate_next_number(
        organization_id=organization.pk,
        name="supplier_bill",
        prefix="BILL-",
        padding=5,
        actor=actor,
    )

    bill = SupplierBill.all_tenants.create(
        organization=organization,
        bill_number=bill_num,
        supplier_reference=supplier_reference,
        supplier=supplier,
        purchase_order=purchase_order,
        goods_receipt=goods_receipt,
        issue_date=issue_date or timezone.now().date(),
        due_date=due_date,
        status=SupplierBillStatus.DRAFT,
        currency=currency,
        notes=notes,
        created_by=actor,
    )

    subtotal_acc = Decimal("0.0000")
    tax_acc = Decimal("0.0000")

    for item in lines:
        product: Product | None = item.get("product")
        desc = item.get("description") or (product.name if product else "Purchased Item")
        qty = _quantize_money(item.get("quantity", "1.0000"))
        unit_price = _quantize_money(item["unit_price"])
        tax_rate = Decimal(str(item.get("tax_rate", "0.00")))

        if qty <= Decimal("0.0000"):
            raise ValidationError(_("Line quantity must be positive."))

        line_sub = _quantize_money(qty * unit_price)
        line_tax = _quantize_money(line_sub * (tax_rate / Decimal("100.00")))
        line_tot = line_sub + line_tax

        SupplierBillLine.all_tenants.create(
            organization=organization,
            bill=bill,
            product=product,
            description=desc,
            quantity=qty,
            unit_price=unit_price,
            tax_rate=tax_rate,
            subtotal=line_sub,
            tax_amount=line_tax,
            total_amount=line_tot,
            created_by=actor,
        )

        subtotal_acc += line_sub
        tax_acc += line_tax

    bill.subtotal = subtotal_acc
    bill.tax_total = tax_acc
    bill.total_amount = subtotal_acc + tax_acc
    bill.balance_due = bill.total_amount
    bill.save(update_fields=["subtotal", "tax_total", "total_amount", "balance_due", "updated_at"])

    events.publish(
        SupplierBillCreated(
            organization_id=organization.pk,
            bill_id=bill.pk,
            bill_number=bill.bill_number,
        )
    )
    return bill


@transaction.atomic
def post_supplier_bill(
    *,
    organization: Organization,
    bill: SupplierBill,
    actor: Any,
) -> SupplierBill:
    """Post supplier bill to general ledger and record AP balance increase on supplier."""
    target_bill = SupplierBill.all_tenants.select_for_update().get(pk=bill.pk, organization=organization)
    if target_bill.status != SupplierBillStatus.DRAFT:
        raise ValidationError(_("Only draft bills can be posted."))

    supplier = Supplier.all_tenants.select_for_update().get(
        pk=target_bill.supplier_id, organization=organization
    )

    # Balanced Double-Entry Journal:
    # Debit: inventory.asset (subtotal)
    # Debit: tax.input (tax_total, if > 0)
    # Credit: ap (total_amount)
    journal_lines = [
        {
            "account": "inventory.asset",
            "debit": target_bill.subtotal,
            "credit": Decimal("0.0000"),
            "description": f"Bill {target_bill.bill_number} goods purchase",
        }
    ]

    if target_bill.tax_total > Decimal("0.0000"):
        journal_lines.append(
            {
                "account": "tax.input",
                "debit": target_bill.tax_total,
                "credit": Decimal("0.0000"),
                "description": f"Bill {target_bill.bill_number} recoverable input VAT",
            }
        )

    journal_lines.append(
        {
            "account": "ap",
            "debit": Decimal("0.0000"),
            "credit": target_bill.total_amount,
            "description": f"Bill {target_bill.bill_number} payable to {supplier.name}",
        }
    )

    entry = accounting_services.post_entry(
        organization=organization,
        date=target_bill.issue_date,
        source=target_bill,
        memo=f"Supplier Bill {target_bill.bill_number} - {supplier.name}",
        lines=journal_lines,
        actor=actor,
    )

    target_bill.journal_entry = entry
    target_bill.status = SupplierBillStatus.POSTED
    target_bill.save(update_fields=["journal_entry", "status", "updated_at"])

    # Increase supplier Accounts Payable balance
    supplier.current_balance += target_bill.total_amount
    supplier.save(update_fields=["current_balance", "updated_at"])

    events.publish(
        SupplierBillPosted(
            organization_id=organization.pk,
            bill_id=target_bill.pk,
            bill_number=target_bill.bill_number,
            total_amount=str(target_bill.total_amount),
            supplier_id=supplier.pk,
        )
    )
    return target_bill


@transaction.atomic
def void_supplier_bill(
    *,
    organization: Organization,
    bill: SupplierBill,
    actor: Any,
) -> SupplierBill:
    """Void a supplier bill and reverse its general ledger entry."""
    target_bill = SupplierBill.all_tenants.select_for_update().get(pk=bill.pk, organization=organization)
    if target_bill.status not in (SupplierBillStatus.DRAFT, SupplierBillStatus.POSTED):
        msg = _("Cannot void bill with status '%(status)s'.") % {"status": target_bill.status}
        raise ValidationError(msg)

    if target_bill.status == SupplierBillStatus.POSTED:
        if target_bill.balance_due < target_bill.total_amount:
            raise ValidationError(_("Cannot void bill with payments already applied."))

        supplier = Supplier.all_tenants.select_for_update().get(
            pk=target_bill.supplier_id, organization=organization
        )

        if target_bill.journal_entry:
            accounting_services.reverse_entry(
                organization=organization,
                entry=target_bill.journal_entry,
                date=timezone.now().date(),
                reason=f"Voiding Supplier Bill {target_bill.bill_number}",
                actor=actor,
            )

        supplier.current_balance -= target_bill.total_amount
        supplier.save(update_fields=["current_balance", "updated_at"])

    target_bill.status = SupplierBillStatus.VOID
    target_bill.balance_due = Decimal("0.0000")
    target_bill.save(update_fields=["status", "balance_due", "updated_at"])
    return target_bill


# =============================================================================
# 5. Supplier Payment Services
# =============================================================================


@transaction.atomic
def record_supplier_payment(
    *,
    organization: Organization,
    supplier: Supplier,
    amount: Decimal | str | float,
    payment_method: str = SupplierPaymentMethod.BANK_TRANSFER,
    payment_date: datetime.date | None = None,
    reference: str = "",
    allocations: list[dict[str, Any]] | None = None,
    notes: str = "",
    actor: Any,
) -> SupplierPayment:
    """Record payment disbursement to a supplier, allocating against bills and posting to ledger."""
    pay_amount = _quantize_money(amount)
    if pay_amount <= Decimal("0.0000"):
        raise ValidationError(_("Payment amount must be strictly positive."))

    supp = Supplier.all_tenants.select_for_update().get(pk=supplier.pk, organization=organization)

    pay_num = generate_next_number(
        organization_id=organization.pk,
        name="supplier_payment",
        prefix="SPAY-",
        padding=5,
        actor=actor,
    )

    payment = SupplierPayment.all_tenants.create(
        organization=organization,
        payment_number=pay_num,
        supplier=supp,
        amount=pay_amount,
        payment_date=payment_date or timezone.now().date(),
        payment_method=payment_method,
        reference=reference,
        notes=notes,
        created_by=actor,
    )

    # Process allocations to posted bills
    if allocations:
        allocated_total = Decimal("0.0000")
        for alloc in allocations:
            bill_id = alloc["bill_id"]
            alloc_amt = _quantize_money(alloc["amount"])
            if alloc_amt <= Decimal("0.0000"):
                continue

            target_bill = SupplierBill.all_tenants.select_for_update().get(
                pk=bill_id, organization=organization
            )
            if target_bill.supplier_id != supp.pk:
                raise ValidationError(_("Cannot allocate payment to bill belonging to another supplier."))
            if target_bill.status not in (SupplierBillStatus.POSTED, SupplierBillStatus.PARTIALLY_PAID):
                raise ValidationError(_("Can only allocate payment against posted or partially paid bills."))
            if alloc_amt > target_bill.balance_due:
                raise ValidationError(
                    _("Allocated amount %(amt)s exceeds bill balance due %(due)s.")
                    % {"amt": alloc_amt, "due": target_bill.balance_due}
                )

            SupplierPaymentAllocation.all_tenants.create(
                organization=organization,
                payment=payment,
                bill=target_bill,
                allocated_amount=alloc_amt,
                created_by=actor,
            )

            target_bill.balance_due -= alloc_amt
            if target_bill.balance_due == Decimal("0.0000"):
                target_bill.status = SupplierBillStatus.PAID
            else:
                target_bill.status = SupplierBillStatus.PARTIALLY_PAID
            target_bill.save(update_fields=["balance_due", "status", "updated_at"])

            allocated_total += alloc_amt

        if allocated_total > pay_amount:
            raise ValidationError(_("Total allocated amounts cannot exceed the payment amount."))

    # Post double-entry journal:
    # Debit: ap (liability reduces)
    # Credit: bank / cash (asset reduces)
    credit_mapping = "cash" if payment_method == SupplierPaymentMethod.CASH else "bank"
    journal_lines = [
        {
            "account": "ap",
            "debit": pay_amount,
            "credit": Decimal("0.0000"),
            "description": f"Payment {payment.payment_number} to {supp.name}",
        },
        {
            "account": credit_mapping,
            "debit": Decimal("0.0000"),
            "credit": pay_amount,
            "description": f"Disbursement for {payment.payment_number}",
        },
    ]

    entry = accounting_services.post_entry(
        organization=organization,
        date=payment.payment_date,
        source=payment,
        memo=f"Supplier Payment {payment.payment_number} - {supp.name}",
        lines=journal_lines,
        actor=actor,
    )

    payment.journal_entry = entry
    payment.save(update_fields=["journal_entry", "updated_at"])

    # Reduce supplier AP balance
    supp.current_balance -= pay_amount
    supp.save(update_fields=["current_balance", "updated_at"])

    events.publish(
        SupplierPaymentRecorded(
            organization_id=organization.pk,
            payment_id=payment.pk,
            payment_number=payment.payment_number,
            amount=str(pay_amount),
            supplier_id=supp.pk,
        )
    )
    return payment


# =============================================================================
# 6. Purchase Return Services
# =============================================================================


@transaction.atomic
def create_purchase_return(
    *,
    organization: Organization,
    supplier: Supplier,
    warehouse: Warehouse,
    goods_receipt: GoodsReceipt | None = None,
    bill: SupplierBill | None = None,
    return_date: datetime.date | None = None,
    lines: list[dict[str, Any]],
    reason: str = "",
    actor: Any,
) -> PurchaseReturn:
    """Create a draft Purchase Return."""
    if not lines:
        raise ValidationError(_("A purchase return requires at least one returned item line."))

    ret_num = generate_next_number(
        organization_id=organization.pk,
        name="purchase_return",
        prefix="PRET-",
        padding=5,
        actor=actor,
    )

    ret = PurchaseReturn.all_tenants.create(
        organization=organization,
        return_number=ret_num,
        supplier=supplier,
        warehouse=warehouse,
        goods_receipt=goods_receipt,
        bill=bill,
        return_date=return_date or timezone.now().date(),
        status=PurchaseReturnStatus.DRAFT,
        reason=reason,
        created_by=actor,
    )

    subtotal_acc = Decimal("0.0000")
    tax_acc = Decimal("0.0000")

    for item in lines:
        product: Product = item["product"]
        qty = _quantize_money(item["quantity"])
        unit_price = _quantize_money(item["unit_price"])
        tax_rate = Decimal(str(item.get("tax_rate", "0.00")))

        if qty <= Decimal("0.0000"):
            raise ValidationError(_("Return quantity must be strictly positive."))

        line_sub = _quantize_money(qty * unit_price)
        line_tax = _quantize_money(line_sub * (tax_rate / Decimal("100.00")))
        line_tot = line_sub + line_tax

        PurchaseReturnLine.all_tenants.create(
            organization=organization,
            purchase_return=ret,
            product=product,
            quantity=qty,
            unit_price=unit_price,
            tax_rate=tax_rate,
            subtotal=line_sub,
            tax_amount=line_tax,
            total_amount=line_tot,
            created_by=actor,
        )

        subtotal_acc += line_sub
        tax_acc += line_tax

    ret.subtotal = subtotal_acc
    ret.tax_total = tax_acc
    ret.total_amount = subtotal_acc + tax_acc
    ret.save(update_fields=["subtotal", "tax_total", "total_amount", "updated_at"])
    return ret


@transaction.atomic
def post_purchase_return(
    *,
    organization: Organization,
    purchase_return: PurchaseReturn,
    actor: Any,
) -> PurchaseReturn:
    """Post a purchase return: dispatches stock back to vendor, credits AP and returns assets."""
    ret = PurchaseReturn.all_tenants.select_for_update().get(pk=purchase_return.pk, organization=organization)
    if ret.status != PurchaseReturnStatus.DRAFT:
        raise ValidationError(_("Only draft returns can be posted."))

    supp = Supplier.all_tenants.select_for_update().get(pk=ret.supplier_id, organization=organization)

    lines = list(PurchaseReturnLine.all_tenants.filter(organization=organization, purchase_return=ret))

    # Dispatch stock out of the warehouse
    for line in lines:
        inventory_services.issue_stock(
            organization=organization,
            warehouse=ret.warehouse,
            product=line.product,
            quantity=line.quantity,
            reference_type="purchase_return",
            reference_id=ret.return_number,
            notes=f"Purchase Return {ret.return_number} to {supp.name}",
            actor=actor,
        )

    # Post balanced ledger entries:
    # Debit: ap (reduces liability to supplier)
    # Credit: inventory.asset (reduces asset)
    # Credit: tax.input (reduces recoverable input tax if any)
    journal_lines = [
        {
            "account": "ap",
            "debit": ret.total_amount,
            "credit": Decimal("0.0000"),
            "description": f"Purchase Return {ret.return_number} adjustment to {supp.name}",
        },
        {
            "account": "inventory.asset",
            "debit": Decimal("0.0000"),
            "credit": ret.subtotal,
            "description": f"Return {ret.return_number} stock decrement",
        },
    ]

    if ret.tax_total > Decimal("0.0000"):
        journal_lines.append(
            {
                "account": "tax.input",
                "debit": Decimal("0.0000"),
                "credit": ret.tax_total,
                "description": f"Return {ret.return_number} tax recovery adjustment",
            }
        )

    entry = accounting_services.post_entry(
        organization=organization,
        date=ret.return_date,
        source=ret,
        memo=f"Purchase Return {ret.return_number} - {supp.name}",
        lines=journal_lines,
        actor=actor,
    )

    ret.journal_entry = entry
    ret.status = PurchaseReturnStatus.POSTED
    ret.save(update_fields=["journal_entry", "status", "updated_at"])

    # Reduce AP liability owed to supplier
    supp.current_balance -= ret.total_amount
    supp.save(update_fields=["current_balance", "updated_at"])

    events.publish(
        PurchaseReturnPosted(
            organization_id=organization.pk,
            return_id=ret.pk,
            return_number=ret.return_number,
            total_amount=str(ret.total_amount),
            supplier_id=supp.pk,
        )
    )
    return ret


@transaction.atomic
def create_purchase_orders_from_reorder_suggestions(
    *,
    organization: Organization,
    warehouse: Warehouse | None = None,
    suggestions: list[dict[str, Any]] | None = None,
    default_supplier_id: int | None = None,
    actor: Any = None,
) -> list[PurchaseOrder]:
    """Generate draft purchase orders grouped by supplier from low-stock reorder suggestions."""
    if suggestions is None:
        suggestions = inventory_selectors.get_reorder_suggestions(
            organization=organization, warehouse=warehouse
        )

    if not suggestions:
        return []

    target_wh = warehouse
    if target_wh is None:
        target_wh = suggestions[0].get("warehouse")
    if target_wh is None:
        target_wh = Warehouse.objects.filter(organization=organization, is_active=True).first()
    if target_wh is None:
        return []

    default_supplier = None
    if default_supplier_id:
        default_supplier = Supplier.all_tenants.filter(
            organization=organization, pk=default_supplier_id
        ).first()
    if default_supplier is None:
        default_supplier = Supplier.all_tenants.filter(organization=organization, is_active=True).first()

    by_supplier: dict[Supplier, list[dict[str, Any]]] = {}

    for sug in suggestions:
        supplier = sug.get("supplier") or default_supplier
        if not supplier:
            continue
        by_supplier.setdefault(supplier, []).append(sug)

    created_pos: list[PurchaseOrder] = []
    for supplier, items in by_supplier.items():
        lines = [
            {
                "product": item["product"],
                "quantity": item["suggested_qty"],
                "unit_price": item["unit_cost"],
            }
            for item in items
        ]
        po = create_purchase_order(
            organization=organization,
            supplier=supplier,
            warehouse=target_wh,
            lines=lines,
            notes=f"Auto-generated draft PO from {target_wh.name} low stock reorder suggestions",
            actor=actor,
        )
        created_pos.append(po)

    return created_pos
