"""Mathematical and subledger invariant tests for customer accounts and running balances."""

import random
from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.customers import services
from apps.customers.models import BalanceEntryType, CustomerBalanceEntry
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")


@pytest.fixture
def cust_org(db: None) -> Organization:
    return Organization.objects.create(name="Customer Invariants Org", slug="cust-inv-org")


@pytest.mark.django_db(transaction=True)
def test_customer_balance_equals_sum_of_debits_minus_credits_invariant(cust_org: Organization) -> None:
    """Invariant: Customer.current_balance == SUM(debit) - SUM(credit) for all ledger entries."""
    customer = services.create_customer(
        organization=cust_org,
        name="Invariant Client",
        opening_balance=Decimal("1000.0000"),
    )

    operations = [
        (BalanceEntryType.INVOICE, Decimal("450.5000"), DECIMAL_ZERO),
        (BalanceEntryType.PAYMENT, DECIMAL_ZERO, Decimal("300.0000")),
        (BalanceEntryType.INVOICE, Decimal("125.2500"), DECIMAL_ZERO),
        (BalanceEntryType.CREDIT_NOTE, DECIMAL_ZERO, Decimal("75.7500")),
        (BalanceEntryType.ADJUSTMENT, Decimal("50.0000"), DECIMAL_ZERO),
        (BalanceEntryType.ADJUSTMENT, DECIMAL_ZERO, Decimal("20.0000")),
        (BalanceEntryType.PAYMENT, DECIMAL_ZERO, Decimal("500.0000")),
        (BalanceEntryType.REFUND, Decimal("150.0000"), DECIMAL_ZERO),
    ]

    for entry_type, debit, credit in operations:
        services.post_customer_transaction(
            organization=cust_org,
            customer=customer,
            entry_type=entry_type,
            debit=debit,
            credit=credit,
        )

    customer.refresh_from_db()

    # Sum of all ledger entries
    sums = CustomerBalanceEntry.all_tenants.filter(customer=customer).aggregate(
        total_debit=Sum("debit"),
        total_credit=Sum("credit"),
    )
    total_debit = sums["total_debit"] or DECIMAL_ZERO
    total_credit = sums["total_credit"] or DECIMAL_ZERO
    expected_balance = total_debit - total_credit

    assert customer.current_balance == expected_balance, (
        f"Invariant broken: customer balance {customer.current_balance} != "
        f"total debit ({total_debit}) - total credit ({total_credit})"
    )


@pytest.mark.django_db(transaction=True)
def test_customer_ledger_chronological_chain_invariant(cust_org: Organization) -> None:
    """Invariant: balance_after[i] == balance_after[i-1] + debit[i] - credit[i]."""
    customer = services.create_customer(
        organization=cust_org,
        name="Sequential Client",
        opening_balance=Decimal("250.0000"),
    )

    rng = random.Random(42)
    current_expected = Decimal("250.0000")

    for step in range(20):
        is_debit = rng.choice([True, False])
        amt = Decimal(str(rng.randint(10, 500)))

        if is_debit:
            services.post_customer_transaction(
                organization=cust_org,
                customer=customer,
                entry_type=BalanceEntryType.INVOICE,
                debit=amt,
                reference_number=f"INV-{step}",
            )
            current_expected += amt
        else:
            services.post_customer_transaction(
                organization=cust_org,
                customer=customer,
                entry_type=BalanceEntryType.PAYMENT,
                credit=amt,
                reference_number=f"PAY-{step}",
            )
            current_expected -= amt

    customer.refresh_from_db()
    assert customer.current_balance == current_expected

    entries = list(CustomerBalanceEntry.all_tenants.filter(customer=customer).order_by("occurred_at", "id"))
    running = Decimal("0.0000")
    for entry in entries:
        running += entry.debit - entry.credit
        assert entry.balance_after == running, (
            f"Chain broken at entry {entry.id}: recorded {entry.balance_after} vs running {running}"
        )
