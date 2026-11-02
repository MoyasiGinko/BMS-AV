"""Business logic services for Point of Sale (POS) operations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.accounting.services import Cr, Dr
from apps.core.events import publish
from apps.core.models import NumberSequence
from apps.core.services import generate_next_number, record_void_document_number
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.customers.models import Customer
from apps.pos.events import (
    CartHeld,
    CartResumed,
    POSSaleCompleted,
    ShiftClosed,
    ShiftOpened,
)
from apps.pos.exceptions import (
    EmptyCartError,
    HeldCartNotFoundError,
    InsufficientTenderError,
    InvalidPaymentTenderError,
    NoOpenShiftError,
    RegisterInactiveError,
    SequenceBlockExhaustedError,
    ShiftAlreadyClosedError,
    ShiftAlreadyOpenError,
)
from apps.pos.models import (
    POSHeldCart,
    POSRegister,
    POSRegisterSequenceBlock,
    POSSale,
    POSShift,
    POSShiftStatus,
)
from apps.sales import services as sales_services
from apps.sales.models import PaymentMethod
from apps.tenancy.models import Branch, Organization, Warehouse

DECIMAL_ZERO = Decimal("0.0000")
FOUR_PLACES = Decimal("0.0001")


@transaction.atomic
def create_register(
    *,
    organization: Organization,
    name: str,
    branch: Branch,
    warehouse: Warehouse,
    code: str | None = None,
    receipt_header: str = "",
    receipt_footer: str = "",
    is_active: bool = True,
    actor: Any = None,
) -> POSRegister:
    """Create a new POS register / checkout terminal."""
    reg_code = code
    if not reg_code:
        reg_code = generate_next_number(
            organization_id=organization.pk,
            name="pos_register",
            prefix="REG-",
            padding=2,
        )

    return POSRegister.objects.create(
        organization=organization,
        code=reg_code,
        name=name,
        branch=branch,
        warehouse=warehouse,
        receipt_header=receipt_header,
        receipt_footer=receipt_footer,
        is_active=is_active,
        created_by=actor,
    )


@transaction.atomic
def open_shift(
    *,
    organization: Organization,
    register: POSRegister,
    cashier: Any,
    opening_cash: Decimal = DECIMAL_ZERO,
    notes: str = "",
    actor: Any = None,
) -> POSShift:
    """Open a cashier shift on a POS register."""
    if not register.is_active:
        raise RegisterInactiveError(f"Register '{register.name}' is inactive and cannot be opened.")

    # Check fiscal period is open
    today = timezone.now().date()
    accounting_services.check_fiscal_period_open(
        organization=organization,
        posting_date=today,
    )

    # Ensure no existing open shift on this register
    existing_open = POSShift.all_tenants.filter(
        organization=organization,
        register=register,
        status=POSShiftStatus.OPEN,
    ).first()
    if existing_open:
        raise ShiftAlreadyOpenError(
            f"Register '{register.name}' already has an active open shift ({existing_open.shift_number})."
        )

    shift_number = generate_next_number(
        organization_id=organization.pk,
        name="pos_shift",
        prefix="SHF-",
        padding=4,
    )

    opening_amt = Decimal(str(opening_cash))
    shift = POSShift.objects.create(
        organization=organization,
        shift_number=shift_number,
        register=register,
        cashier=cashier,
        status=POSShiftStatus.OPEN,
        opened_at=timezone.now(),
        opening_cash=opening_amt,
        expected_cash=opening_amt,
        notes=notes,
        created_by=actor,
    )

    publish(
        ShiftOpened(
            organization_id=organization.pk,
            shift_id=shift.pk,
            shift_number=shift.shift_number,
            register_id=register.pk,
            cashier_id=cashier.pk if hasattr(cashier, "pk") else 0,
            opening_cash=str(shift.opening_cash),
        )
    )

    return shift


@transaction.atomic
def close_shift(
    *,
    organization: Organization,
    shift: POSShift,
    closing_cash_counted: Decimal,
    notes: str = "",
    actor: Any = None,
) -> POSShift:
    """Close an open cashier shift, calculate cash variance, and record GL variance entry if any."""
    shift = POSShift.all_tenants.select_for_update().get(pk=shift.pk, organization=organization)
    if shift.status != POSShiftStatus.OPEN:
        raise ShiftAlreadyClosedError(f"Shift '{shift.shift_number}' is already closed.")

    today = timezone.now().date()
    accounting_services.check_fiscal_period_open(
        organization=organization,
        posting_date=today,
    )

    counted_cash = Decimal(str(closing_cash_counted))
    expected_cash = shift.expected_cash
    variance = counted_cash - expected_cash

    variance_entry = None
    if variance != DECIMAL_ZERO:
        # Post double-entry journal entry for cash variance
        # Overage (> 0): Dr cash, Cr suspense (or overage revenue)
        # Shortage (< 0): Dr suspense (or cash shortage expense), Cr cash
        abs_var = abs(variance)
        if variance > DECIMAL_ZERO:
            journal_lines = [
                Dr("cash", abs_var, memo=f"Shift {shift.shift_number} Cash Overage"),
                Cr("suspense", abs_var, memo=f"Shift {shift.shift_number} Cash Overage Clearing"),
            ]
        else:
            journal_lines = [
                Dr("suspense", abs_var, memo=f"Shift {shift.shift_number} Cash Shortage Clearing"),
                Cr("cash", abs_var, memo=f"Shift {shift.shift_number} Cash Shortage"),
            ]

        variance_entry = accounting_services.post_entry(
            organization=organization,
            date=today,
            lines=journal_lines,
            memo=f"POS Shift Cash Variance - {shift.shift_number}",
            actor=actor,
        )

    shift.status = POSShiftStatus.CLOSED
    shift.closed_at = timezone.now()
    shift.closing_cash_counted = counted_cash
    shift.cash_variance = variance
    shift.variance_journal_entry = variance_entry
    if notes:
        shift.notes = f"{shift.notes}\nClosing Notes: {notes}".strip()
    shift.save(
        update_fields=[
            "status",
            "closed_at",
            "closing_cash_counted",
            "cash_variance",
            "variance_journal_entry",
            "notes",
            "updated_at",
        ]
    )

    publish(
        ShiftClosed(
            organization_id=organization.pk,
            shift_id=shift.pk,
            shift_number=shift.shift_number,
            closing_cash_counted=str(shift.closing_cash_counted),
            expected_cash=str(shift.expected_cash),
            cash_variance=str(shift.cash_variance),
        )
    )

    return shift


def _get_or_create_walk_in_customer(organization: Organization, actor: Any) -> Customer:
    """Find or create default Walk-in Customer for counter sales."""
    customer = Customer.all_tenants.filter(organization=organization, name__iexact="Walk-in Customer").first()
    if not customer:
        customer = customers_services.create_customer(
            organization=organization,
            name="Walk-in Customer",
            actor=actor,
        )
    return customer


@transaction.atomic
def checkout_pos_sale(
    *,
    organization: Organization,
    shift: POSShift,
    lines: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    customer: Customer | None = None,
    amount_tendered: Decimal | None = None,
    notes: str = "",
    actor: Any = None,
) -> POSSale:
    """Execute complete POS checkout: atomic invoice creation, posting, stock issue, and payments."""
    shift = POSShift.all_tenants.select_for_update().get(pk=shift.pk, organization=organization)
    if shift.status != POSShiftStatus.OPEN:
        raise NoOpenShiftError(f"Shift '{shift.shift_number}' is closed. An open shift is required.")

    if not lines:
        raise EmptyCartError("Cannot checkout with an empty cart.")

    if not payments:
        raise InvalidPaymentTenderError("At least one payment tender is required.")

    with tenant_context(organization):
        # 1. Resolve Customer
        sale_customer = customer or _get_or_create_walk_in_customer(organization, actor)

        # 2. Create and Post Sales Invoice (reusing apps.sales services)
        # This automatically updates inventory stock levels and posts GL COGS/revenue entries.
        register = shift.register
        invoice = sales_services.create_invoice(
            organization=organization,
            customer=sale_customer,
            warehouse=register.warehouse,
            lines=lines,
            branch=register.branch,
            notes=f"POS Sale on Register {register.code}",
            actor=actor,
        )

        # Validate tenders vs grand_total before posting (comparing with standard cent tolerance)
        total_paid = sum(Decimal(str(p.get("amount", DECIMAL_ZERO))) for p in payments)
        if total_paid.quantize(Decimal("0.01")) < invoice.grand_total.quantize(Decimal("0.01")):
            raise InsufficientTenderError(
                f"Total payment tendered (${total_paid}) is less than invoice total (${invoice.grand_total})."
            )

        sales_services.post_invoice(organization=organization, invoice=invoice, actor=actor)
        invoice.refresh_from_db()

    tendered_input = Decimal(str(amount_tendered)) if amount_tendered is not None else total_paid
    change_given = max(DECIMAL_ZERO, tendered_input.quantize(Decimal("0.01")) - invoice.grand_total.quantize(Decimal("0.01")))

    # 4. Receive and allocate payments against invoice
    # If customer paid more in cash than total, record the exact invoice allocation
    remaining_to_allocate = min(invoice.grand_total, total_paid)
    tender_summaries: list[str] = []

    shift_cash_delta = DECIMAL_ZERO
    shift_card_delta = DECIMAL_ZERO
    shift_other_delta = DECIMAL_ZERO

    for p_item in payments:
        raw_amt = Decimal(str(p_item.get("amount", DECIMAL_ZERO)))
        if raw_amt <= DECIMAL_ZERO:
            continue

        method = p_item.get("payment_method", PaymentMethod.CASH)
        tender_summaries.append(f"{method}: ${raw_amt}")

        # Amount to apply to invoice for this tender
        alloc_amt = min(raw_amt, remaining_to_allocate)
        if alloc_amt > DECIMAL_ZERO:
            sales_services.receive_payment(
                organization=organization,
                customer=sale_customer,
                amount=alloc_amt,
                payment_method=method,
                allocations=[{"invoice_id": invoice.id, "amount": alloc_amt}],
                branch=register.branch,
                reference=f"POS-{register.code}",
                actor=actor,
            )
            remaining_to_allocate -= alloc_amt

        # Tally shift cash / card collected
        if method in (PaymentMethod.CASH, "cash"):
            shift_cash_delta += alloc_amt
        elif method in (PaymentMethod.CREDIT_CARD, PaymentMethod.DEBIT_CARD, "card", "credit_card", "debit_card"):
            shift_card_delta += alloc_amt
        else:
            shift_other_delta += alloc_amt

    invoice.refresh_from_db()

    # 5. Record POSSale
    receipt_number = generate_next_number(
        organization_id=organization.pk,
        name="pos_receipt",
        prefix="REC-",
        padding=4,
    )

    sale = POSSale.objects.create(
        organization=organization,
        receipt_number=receipt_number,
        shift=shift,
        register=register,
        cashier=actor if actor and hasattr(actor, "pk") else shift.cashier,
        customer=sale_customer,
        invoice=invoice,
        subtotal=invoice.subtotal,
        discount_total=invoice.discount_total,
        tax_total=invoice.tax_total,
        grand_total=invoice.grand_total,
        amount_tendered=tendered_input,
        change_given=change_given,
        payment_methods_summary=", ".join(tender_summaries),
        notes=notes,
        created_by=actor,
    )

    # 6. Update Shift metrics
    shift.total_sales += invoice.grand_total
    shift.total_cash_collected += shift_cash_delta
    shift.total_card_collected += shift_card_delta
    shift.total_other_collected += shift_other_delta
    shift.expected_cash = shift.opening_cash + shift.total_cash_collected
    shift.order_count += 1
    shift.save(
        update_fields=[
            "total_sales",
            "total_cash_collected",
            "total_card_collected",
            "total_other_collected",
            "expected_cash",
            "order_count",
            "updated_at",
        ]
    )

    publish(
        POSSaleCompleted(
            organization_id=organization.pk,
            sale_id=sale.pk,
            receipt_number=sale.receipt_number,
            invoice_id=invoice.pk,
            grand_total=str(sale.grand_total),
            cashier_id=sale.cashier.pk if hasattr(sale.cashier, "pk") else 0,
        )
    )

    return sale


@transaction.atomic
def hold_cart(
    *,
    organization: Organization,
    shift: POSShift,
    cart_data: dict[str, Any],
    cart_label: str = "Customer 1",
    customer: Customer | None = None,
    total_amount: Decimal = DECIMAL_ZERO,
    actor: Any = None,
) -> POSHeldCart:
    """Park a cart so the cashier can serve another customer and resume later."""
    held = POSHeldCart.objects.create(
        organization=organization,
        shift=shift,
        cart_label=cart_label,
        customer=customer,
        cart_data=cart_data,
        total_amount=Decimal(str(total_amount)),
        created_by=actor,
    )
    publish(CartHeld(organization_id=organization.pk, held_cart_id=held.pk, shift_id=shift.pk))
    return held


@transaction.atomic
def resume_cart(
    *,
    organization: Organization,
    held_cart_id: int,
    actor: Any = None,
) -> dict[str, Any]:
    """Retrieve and delete a held cart to resume checkout."""
    held = POSHeldCart.all_tenants.filter(organization=organization, pk=held_cart_id).first()
    if not held:
        raise HeldCartNotFoundError("Held cart not found or already resumed.")

    cart_info = {
        "cart_label": held.cart_label,
        "customer_id": held.customer_id,
        "cart_data": held.cart_data,
        "total_amount": held.total_amount,
    }
    shift_id = held.shift_id
    held.delete()

    publish(CartResumed(organization_id=organization.pk, held_cart_id=held_cart_id, shift_id=shift_id))
    return cart_info


@transaction.atomic
def allocate_register_sequence_block(
    *,
    organization: Organization,
    register: POSRegister,
    sequence_name: str = "pos_receipt",
    block_size: int = 100,
    actor: Any = None,
) -> POSRegisterSequenceBlock:
    """Pre-allocate a sequential range of receipt/invoice numbers for an offline POS register."""
    if not register.is_active:
        raise RegisterInactiveError(f"Register '{register.code}' is inactive.")
    if block_size < 1:
        raise ValueError("Block size must be at least 1.")

    # Scoped to organization using all_tenants for execution outside request thread context
    seq = (
        NumberSequence.all_tenants.select_for_update()
        .filter(organization=organization, name=sequence_name)
        .first()
    )
    if seq is None:
        seq = NumberSequence.all_tenants.create(
            organization=organization,
            name=sequence_name,
            prefix=f"REC-{register.code}-",
            padding=5,
            next_number=1,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )

    start = seq.next_number
    end = start + block_size - 1
    seq.next_number += block_size
    seq.save(update_fields=["next_number", "updated_at"])

    # Scoped to organization using all_tenants for execution outside request thread context
    block = POSRegisterSequenceBlock.all_tenants.create(
        organization=organization,
        register=register,
        sequence=seq,
        range_start=start,
        range_end=end,
        next_number=start,
        is_active=True,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return block


@transaction.atomic
def consume_next_number_from_block(
    *,
    block: POSRegisterSequenceBlock,
) -> tuple[int, str]:
    """Atomically consume the next number in an allocated block and return (int_val, formatted_string)."""
    # Lock block row
    locked_block = (
        POSRegisterSequenceBlock.all_tenants.select_for_update()
        .filter(pk=block.pk)
        .first()
    )
    if not locked_block or not locked_block.is_active or locked_block.next_number > locked_block.range_end:
        if locked_block and locked_block.is_active:
            locked_block.is_active = False
            locked_block.save(update_fields=["is_active", "updated_at"])
        raise SequenceBlockExhaustedError("Allocated sequence block range is exhausted.")

    current_val = locked_block.next_number
    num_str = str(current_val).zfill(locked_block.sequence.padding)
    formatted = f"{locked_block.sequence.prefix}{num_str}{locked_block.sequence.suffix}"

    locked_block.next_number += 1
    if locked_block.next_number > locked_block.range_end:
        locked_block.is_active = False
    locked_block.save(update_fields=["next_number", "is_active", "updated_at"])

    # Update in-memory reference
    block.next_number = locked_block.next_number
    block.is_active = locked_block.is_active

    return current_val, formatted


@transaction.atomic
def record_register_block_gaps(
    *,
    block: POSRegisterSequenceBlock,
    used_numbers: set[int],
    reason: str = "Offline synchronization gap",
    actor: Any = None,
) -> list[Any]:
    """Inspect synchronized numbers against the block range and record any skipped numbers as void."""
    if not used_numbers:
        return []

    max_used = max(used_numbers)
    if max_used < block.range_start:
        return []

    void_entries = []
    limit = min(max_used, block.range_end)
    for num in range(block.range_start, limit + 1):
        if num not in used_numbers:
            num_str = str(num).zfill(block.sequence.padding)
            formatted = f"{block.sequence.prefix}{num_str}{block.sequence.suffix}"
            void_record = record_void_document_number(
                organization_id=block.organization_id,
                sequence=block.sequence,
                document_number=formatted,
                sequence_number=num,
                reason=reason,
                source=f"POS Register {block.register.code}",
                actor=actor,
            )
            void_entries.append(void_record)
    return void_entries
