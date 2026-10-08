"""Domain business logic for customer relationship, credit checks, and subledger posting."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import PriceList
from apps.core.events import publish
from apps.core.services import generate_next_number
from apps.customers.events import (
    CustomerBalanceChanged,
    CustomerCreated,
    CustomerCreditLimitExceeded,
    CustomerUpdated,
)
from apps.customers.exceptions import (
    CreditLimitExceeded,
    CustomerHasTransactions,
    CustomerNotFoundError,
    CustomerSuspended,
    InvalidBalanceMutation,
)
from apps.customers.models import (
    AddressType,
    BalanceEntryType,
    Customer,
    CustomerAddress,
    CustomerBalanceEntry,
    CustomerContact,
    CustomerStatus,
    CustomerType,
)
from apps.tenancy.models import Organization


@transaction.atomic
def create_customer(
    *,
    organization: Organization,
    name: str,
    code: str | None = None,
    type: str = CustomerType.INDIVIDUAL,
    status: str = CustomerStatus.ACTIVE,
    email: str = "",
    phone: str = "",
    tax_id: str = "",
    currency: str = "USD",
    price_list: PriceList | None = None,
    credit_limit: Decimal = Decimal("0.0000"),
    payment_terms_days: int = 0,
    opening_balance: Decimal = Decimal("0.0000"),
    notes: str = "",
    actor: Any = None,
) -> Customer:
    """Create a new customer account with optional opening AR balance."""
    if not code:
        code = generate_next_number(
            organization_id=organization.pk,
            name="customer",
            prefix="CUST-",
            padding=4,
        )

    customer = Customer.objects.create(
        organization=organization,
        code=code,
        name=name,
        type=type,
        status=status,
        email=email,
        phone=phone,
        tax_id=tax_id,
        currency=currency,
        price_list=price_list,
        credit_limit=credit_limit,
        payment_terms_days=payment_terms_days,
        notes=notes,
        created_by=actor,
    )

    if opening_balance > Decimal("0.0000"):
        post_customer_transaction(
            organization=organization,
            customer=customer,
            entry_type=BalanceEntryType.OPENING_BALANCE,
            debit=opening_balance,
            credit=Decimal("0.0000"),
            description="Opening AR balance",
            actor=actor,
            check_credit=False,
        )
        customer.refresh_from_db()

    publish(
        CustomerCreated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            customer_id=customer.pk,
            code=customer.code,
            name=customer.name,
        )
    )

    return customer


@transaction.atomic
def update_customer(
    *,
    organization: Organization,
    customer: Customer,
    name: str | None = None,
    type: str | None = None,
    status: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    tax_id: str | None = None,
    currency: str | None = None,
    price_list: PriceList | None = None,
    credit_limit: Decimal | None = None,
    payment_terms_days: int | None = None,
    notes: str | None = None,
    actor: Any = None,
) -> Customer:
    """Update customer details and credit terms."""
    if customer.organization_id != organization.pk:
        raise CustomerNotFoundError("Customer belongs to a different organization.")

    update_fields = ["updated_at"]

    if name is not None:
        customer.name = name
        update_fields.append("name")
    if type is not None:
        customer.type = type
        update_fields.append("type")
    if status is not None:
        customer.status = status
        update_fields.append("status")
    if email is not None:
        customer.email = email
        update_fields.append("email")
    if phone is not None:
        customer.phone = phone
        update_fields.append("phone")
    if tax_id is not None:
        customer.tax_id = tax_id
        update_fields.append("tax_id")
    if currency is not None:
        customer.currency = currency
        update_fields.append("currency")
    if price_list is not None or "price_list" in locals():
        customer.price_list = price_list
        update_fields.append("price_list")
    if credit_limit is not None:
        customer.credit_limit = credit_limit
        update_fields.append("credit_limit")
    if payment_terms_days is not None:
        customer.payment_terms_days = payment_terms_days
        update_fields.append("payment_terms_days")
    if notes is not None:
        customer.notes = notes
        update_fields.append("notes")

    customer.save(update_fields=update_fields)

    publish(
        CustomerUpdated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            customer_id=customer.pk,
            code=customer.code,
            name=customer.name,
        )
    )

    return customer


@transaction.atomic
def delete_customer(*, organization: Organization, customer: Customer, actor: Any = None) -> None:
    """Delete a customer only if no transaction history exists."""
    if customer.organization_id != organization.pk:
        raise CustomerNotFoundError("Customer belongs to a different organization.")

    if CustomerBalanceEntry.all_tenants.filter(organization=organization, customer=customer).exists():
        raise CustomerHasTransactions("Cannot delete customer with transaction or balance history.")

    customer.delete()


@transaction.atomic
def add_customer_address(
    *,
    organization: Organization,
    customer: Customer,
    line1: str,
    city: str,
    line2: str = "",
    state_or_province: str = "",
    postal_code: str = "",
    country: str = "US",
    recipient_name: str = "",
    phone: str = "",
    type: str = AddressType.BILLING,
    is_default: bool = False,
    actor: Any = None,
) -> CustomerAddress:
    """Add a structured address to a customer account."""
    if customer.organization_id != organization.pk:
        raise CustomerNotFoundError("Customer belongs to a different organization.")

    if is_default:
        CustomerAddress.all_tenants.filter(
            organization=organization,
            customer=customer,
            type=type,
            is_default=True,
        ).update(is_default=False)

    return CustomerAddress.objects.create(
        organization=organization,
        customer=customer,
        type=type,
        recipient_name=recipient_name,
        line1=line1,
        line2=line2,
        city=city,
        state_or_province=state_or_province,
        postal_code=postal_code,
        country=country,
        phone=phone,
        is_default=is_default,
        created_by=actor,
    )


@transaction.atomic
def add_customer_contact(
    *,
    organization: Organization,
    customer: Customer,
    first_name: str,
    last_name: str = "",
    email: str = "",
    phone: str = "",
    title: str = "",
    is_primary: bool = False,
    notes: str = "",
    actor: Any = None,
) -> CustomerContact:
    """Add a contact person to a customer account."""
    if customer.organization_id != organization.pk:
        raise CustomerNotFoundError("Customer belongs to a different organization.")

    if is_primary:
        CustomerContact.all_tenants.filter(
            organization=organization,
            customer=customer,
            is_primary=True,
        ).update(is_primary=False)

    return CustomerContact.objects.create(
        organization=organization,
        customer=customer,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        title=title,
        is_primary=is_primary,
        notes=notes,
        created_by=actor,
    )


def check_credit_limit(
    *,
    customer: Customer,
    additional_amount: Decimal,
) -> tuple[bool, Decimal, Decimal]:
    """Inspect customer credit limit against current balance plus proposed amount.

    Returns: (is_allowed, current_balance, credit_limit)
    """
    if customer.status == CustomerStatus.SUSPENDED:
        return False, customer.current_balance, customer.credit_limit

    if not customer.has_credit_terms:
        # Cash/prepaid: allowed if additional amount is zero or negative (payments/credits),
        # or if organization allows cash transactions
        return True, customer.current_balance, customer.credit_limit

    proposed_balance = customer.current_balance + additional_amount
    is_allowed = proposed_balance <= customer.credit_limit
    return is_allowed, customer.current_balance, customer.credit_limit


@transaction.atomic
def post_customer_transaction(
    *,
    organization: Organization,
    customer: Customer,
    entry_type: str,
    debit: Decimal = Decimal("0.0000"),
    credit: Decimal = Decimal("0.0000"),
    reference_type: str = "",
    reference_id: str = "",
    reference_number: str = "",
    description: str = "",
    occurred_at: datetime.datetime | None = None,
    actor: Any = None,
    check_credit: bool = True,
) -> CustomerBalanceEntry:
    """Post an immutable financial entry to the customer balance ledger.

    Row-locks Customer to guarantee linear running balances and avoid race conditions.
    """
    if debit < Decimal("0.0000") or credit < Decimal("0.0000"):
        raise InvalidBalanceMutation("Debit and credit amounts cannot be negative.")
    if debit == Decimal("0.0000") and credit == Decimal("0.0000"):
        raise InvalidBalanceMutation("Either debit or credit must be positive.")
    if debit > Decimal("0.0000") and credit > Decimal("0.0000"):
        raise InvalidBalanceMutation("Cannot specify both debit and credit.")

    # Acquire lock on Customer row
    locked_cust = (
        Customer.all_tenants.select_for_update().filter(organization=organization, pk=customer.pk).first()
    )
    if not locked_cust:
        raise CustomerNotFoundError(f"Customer {customer.pk} not found in organization.")

    # Debit increases AR (invoices/charges). Check status and credit limit
    if debit > Decimal("0.0000"):
        if locked_cust.status == CustomerStatus.SUSPENDED:
            raise CustomerSuspended(f"Customer {locked_cust.name} ({locked_cust.code}) is suspended.")

        if check_credit and locked_cust.has_credit_terms:
            proposed_balance = locked_cust.current_balance + debit - credit
            if proposed_balance > locked_cust.credit_limit:
                publish(
                    CustomerCreditLimitExceeded(
                        organization_id=organization.pk,
                        actor_id=getattr(actor, "pk", None),
                        customer_id=locked_cust.pk,
                        proposed_amount=str(debit),
                        current_balance=str(locked_cust.current_balance),
                        credit_limit=str(locked_cust.credit_limit),
                    )
                )
                raise CreditLimitExceeded(
                    f"Transaction exceeds credit limit of {locked_cust.credit_limit} "
                    f"(Current: {locked_cust.current_balance}, Proposed: {proposed_balance})."
                )

    new_balance = locked_cust.current_balance + debit - credit
    tx_time = occurred_at or timezone.now()

    entry = CustomerBalanceEntry.objects.create(
        organization=organization,
        customer=locked_cust,
        entry_type=entry_type,
        debit=debit,
        credit=credit,
        balance_after=new_balance,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_number=reference_number,
        description=description,
        occurred_at=tx_time,
        created_by=actor,
    )

    update_fields = ["current_balance", "updated_at"]
    locked_cust.current_balance = new_balance

    if entry_type in (BalanceEntryType.INVOICE, BalanceEntryType.OPENING_BALANCE):
        locked_cust.total_spent += debit
        update_fields.append("total_spent")

    locked_cust.save(update_fields=update_fields)

    publish(
        CustomerBalanceChanged(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            customer_id=locked_cust.pk,
            entry_id=entry.pk,
            entry_type=entry_type,
            debit=str(debit),
            credit=str(credit),
            new_balance=str(new_balance),
            reference_type=reference_type,
            reference_id=reference_id,
        )
    )

    return entry


@transaction.atomic
def adjust_customer_balance(
    *,
    organization: Organization,
    customer: Customer,
    adjustment_type: str,  # 'debit' or 'credit'
    amount: Decimal,
    reason: str,
    reference_number: str = "",
    actor: Any = None,
) -> CustomerBalanceEntry:
    """Manual AR balance adjustment with justification."""
    if amount <= Decimal("0.0000"):
        raise InvalidBalanceMutation("Adjustment amount must be positive.")

    debit = amount if adjustment_type == "debit" else Decimal("0.0000")
    credit = amount if adjustment_type == "credit" else Decimal("0.0000")

    return post_customer_transaction(
        organization=organization,
        customer=customer,
        entry_type=BalanceEntryType.ADJUSTMENT,
        debit=debit,
        credit=credit,
        reference_type="manual_adjustment",
        reference_number=reference_number,
        description=f"Manual Adjustment: {reason}",
        actor=actor,
        check_credit=False,
    )


def reconcile_customer_balance(
    *,
    organization: Organization,
    customer: Customer,
    auto_repair: bool = False,
) -> dict[str, Any]:
    """Compare customer cached balance with ledger sum."""
    totals = CustomerBalanceEntry.all_tenants.filter(organization=organization, customer=customer).aggregate(
        total_debit=Sum("debit"),
        total_credit=Sum("credit"),
    )
    tot_dr = totals["total_debit"] or Decimal("0.0000")
    tot_cr = totals["total_credit"] or Decimal("0.0000")
    ledger_balance = tot_dr - tot_cr

    is_reconciled = customer.current_balance == ledger_balance
    variance = customer.current_balance - ledger_balance

    if not is_reconciled and auto_repair:
        Customer.all_tenants.filter(pk=customer.pk).update(current_balance=ledger_balance)
        customer.current_balance = ledger_balance

    return {
        "customer_id": customer.pk,
        "cached_balance": customer.current_balance,
        "ledger_balance": ledger_balance,
        "is_reconciled": is_reconciled,
        "variance": variance,
    }
