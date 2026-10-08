"""Comprehensive unit tests for customer services, balance ledger, and credit limits."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.models import PriceList
from apps.customers import services
from apps.customers.exceptions import (
    CreditLimitExceeded,
    CustomerHasTransactions,
    CustomerSuspended,
    InvalidBalanceMutation,
)
from apps.customers.models import (
    AddressType,
    BalanceEntryType,
    Customer,
    CustomerBalanceEntry,
    CustomerStatus,
    CustomerType,
)
from apps.tenancy.models import Organization


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="Customer Test Org", slug="cust-test-org")


@pytest.fixture
def org_b() -> Organization:
    return Organization.objects.create(name="Customer Org B", slug="cust-org-b")


@pytest.fixture
def price_list(org: Organization) -> PriceList:
    return PriceList.objects.create(
        organization=org,
        name="VIP Wholesale",
        currency="USD",
        is_active=True,
    )


@pytest.mark.django_db
class TestCustomerServices:
    def test_create_customer_minimal(self, org: Organization) -> None:
        customer = services.create_customer(
            organization=org,
            name="Alpha Corp",
        )
        assert customer.pk is not None
        assert customer.organization == org
        assert customer.name == "Alpha Corp"
        assert customer.code.startswith("CUST-")
        assert customer.type == CustomerType.INDIVIDUAL
        assert customer.status == CustomerStatus.ACTIVE
        assert customer.current_balance == Decimal("0.0000")
        assert customer.credit_limit == Decimal("0.0000")
        assert customer.currency == "USD"

    def test_create_customer_with_custom_code_and_opening_balance(
        self, org: Organization, price_list: PriceList
    ) -> None:
        customer = services.create_customer(
            organization=org,
            name="Beta LLC",
            code="CUST-9999",
            type=CustomerType.BUSINESS,
            email="billing@beta.example",
            phone="+1 555-0199",
            tax_id="US987654321",
            currency="USD",
            price_list=price_list,
            credit_limit=Decimal("5000.0000"),
            payment_terms_days=30,
            opening_balance=Decimal("1250.5000"),
            notes="Key enterprise client",
        )
        assert customer.code == "CUST-9999"
        assert customer.type == CustomerType.BUSINESS
        assert customer.price_list == price_list
        assert customer.current_balance == Decimal("1250.5000")

        # Verify balance entry created
        ledger = CustomerBalanceEntry.all_tenants.filter(customer=customer)
        assert ledger.count() == 1
        entry = ledger.first()
        assert entry is not None
        assert entry.entry_type == BalanceEntryType.OPENING_BALANCE
        assert entry.debit == Decimal("1250.5000")
        assert entry.credit == Decimal("0.0000")
        assert entry.balance_after == Decimal("1250.5000")

    def test_update_customer(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Initial Name")
        updated = services.update_customer(
            organization=org,
            customer=customer,
            name="Updated Name",
            status=CustomerStatus.INACTIVE,
            credit_limit=Decimal("1000.0000"),
            payment_terms_days=15,
        )
        assert updated.name == "Updated Name"
        assert updated.status == CustomerStatus.INACTIVE
        assert updated.credit_limit == Decimal("1000.0000")
        assert updated.payment_terms_days == 15

    def test_delete_customer_without_transactions(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Disposable Co")
        cust_id = customer.pk
        services.delete_customer(organization=org, customer=customer)
        assert not Customer.objects.filter(pk=cust_id).exists()

    def test_delete_customer_with_transactions_fails(self, org: Organization) -> None:
        customer = services.create_customer(
            organization=org,
            name="Active Co",
            opening_balance=Decimal("100.0000"),
        )
        with pytest.raises(CustomerHasTransactions):
            services.delete_customer(organization=org, customer=customer)

    def test_add_customer_address(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Acme Logistics")
        addr1 = services.add_customer_address(
            organization=org,
            customer=customer,
            type=AddressType.BILLING,
            recipient_name="Acme Finance",
            line1="123 Market St",
            city="San Francisco",
            state_or_province="CA",
            postal_code="94105",
            country="US",
            is_default=True,
        )
        assert addr1.pk is not None
        assert addr1.organization == org
        assert addr1.customer == customer
        assert addr1.is_default is True

        # Adding another default billing address sets previous to False
        addr2 = services.add_customer_address(
            organization=org,
            customer=customer,
            type=AddressType.BILLING,
            recipient_name="Acme AP",
            line1="456 Mission St",
            city="San Francisco",
            state_or_province="CA",
            postal_code="94105",
            country="US",
            is_default=True,
        )
        addr1.refresh_from_db()
        assert addr1.is_default is False
        assert addr2.is_default is True

    def test_add_customer_contact(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Tech Supply")
        c1 = services.add_customer_contact(
            organization=org,
            customer=customer,
            first_name="Jane",
            last_name="Doe",
            title="Procurement Director",
            email="jane@techsupply.example",
            phone="+1 555-0101",
            is_primary=True,
        )
        assert c1.pk is not None
        assert c1.organization == org
        assert c1.customer == customer
        assert c1.is_primary is True

        # Adding second primary contact resets first
        c2 = services.add_customer_contact(
            organization=org,
            customer=customer,
            first_name="John",
            last_name="Smith",
            title="VP Operations",
            email="john@techsupply.example",
            phone="+1 555-0102",
            is_primary=True,
        )
        c1.refresh_from_db()
        assert c1.is_primary is False
        assert c2.is_primary is True


@pytest.mark.django_db
class TestCustomerBalanceLedger:
    def test_post_transactions_and_running_balance(self, org: Organization) -> None:
        customer = services.create_customer(
            organization=org,
            name="Retail Partner",
            credit_limit=Decimal("10000.0000"),
        )

        # Post invoice (debit increases balance)
        e1 = services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("500.0000"),
            reference_number="INV-001",
            description="First delivery",
        )
        customer.refresh_from_db()
        assert e1.balance_after == Decimal("500.0000")
        assert customer.current_balance == Decimal("500.0000")

        # Post payment (credit decreases balance)
        e2 = services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.PAYMENT,
            credit=Decimal("200.0000"),
            reference_number="PAY-001",
            description="Partial payment",
        )
        customer.refresh_from_db()
        assert e2.balance_after == Decimal("300.0000")
        assert customer.current_balance == Decimal("300.0000")

        # Post credit note
        e3 = services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.CREDIT_NOTE,
            credit=Decimal("50.0000"),
            reference_number="CN-001",
            description="Damaged item rebate",
        )
        customer.refresh_from_db()
        assert e3.balance_after == Decimal("250.0000")
        assert customer.current_balance == Decimal("250.0000")

    def test_invalid_mutation_raises(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Test Co")

        with pytest.raises(InvalidBalanceMutation, match="Either debit or credit must be positive"):
            services.post_customer_transaction(
                organization=org,
                customer=customer,
                entry_type=BalanceEntryType.INVOICE,
                debit=Decimal("0.0000"),
                credit=Decimal("0.0000"),
            )

        with pytest.raises(InvalidBalanceMutation, match="Cannot specify both debit and credit"):
            services.post_customer_transaction(
                organization=org,
                customer=customer,
                entry_type=BalanceEntryType.INVOICE,
                debit=Decimal("100.0000"),
                credit=Decimal("50.0000"),
            )

        with pytest.raises(InvalidBalanceMutation, match="Debit and credit amounts cannot be negative"):
            services.post_customer_transaction(
                organization=org,
                customer=customer,
                entry_type=BalanceEntryType.INVOICE,
                debit=Decimal("-10.0000"),
            )

    def test_suspended_customer_rejects_new_debit(self, org: Organization) -> None:
        customer = services.create_customer(
            organization=org,
            name="Frozen Client",
            status=CustomerStatus.SUSPENDED,
        )

        with pytest.raises(CustomerSuspended):
            services.post_customer_transaction(
                organization=org,
                customer=customer,
                entry_type=BalanceEntryType.INVOICE,
                debit=Decimal("150.0000"),
            )

        # Suspended customer CAN still make payments (credit)
        entry = services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.PAYMENT,
            credit=Decimal("50.0000"),
            reference_number="PAY-SUSP",
        )
        assert entry.pk is not None

    def test_credit_limit_enforcement(self, org: Organization) -> None:
        customer = services.create_customer(
            organization=org,
            name="Credit Limited Co",
            credit_limit=Decimal("500.0000"),
        )

        # Check passes within limit
        allowed, _cur_bal, _limit = services.check_credit_limit(
            customer=customer,
            additional_amount=Decimal("400.0000"),
        )
        assert allowed is True

        # Within limit post
        services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("400.0000"),
        )

        customer.refresh_from_db()
        # Check fails over limit
        allowed, _cur_bal, _limit = services.check_credit_limit(
            customer=customer,
            additional_amount=Decimal("200.0000"),
        )
        assert allowed is False

        # Posting over limit fails
        with pytest.raises(CreditLimitExceeded):
            services.post_customer_transaction(
                organization=org,
                customer=customer,
                entry_type=BalanceEntryType.INVOICE,
                debit=Decimal("200.0000"),
            )

    def test_manual_adjustment(self, org: Organization) -> None:
        customer = services.create_customer(
            organization=org,
            name="Audit Adjustment Co",
        )

        # Debit adjustment
        d_entry = services.adjust_customer_balance(
            organization=org,
            customer=customer,
            adjustment_type="debit",
            amount=Decimal("120.0000"),
            reference_number="ADJ-D1",
            reason="Late fee assessment",
        )
        assert d_entry.debit == Decimal("120.0000")
        assert d_entry.entry_type == BalanceEntryType.ADJUSTMENT
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("120.0000")

        # Credit adjustment
        c_entry = services.adjust_customer_balance(
            organization=org,
            customer=customer,
            adjustment_type="credit",
            amount=Decimal("20.0000"),
            reference_number="ADJ-C1",
            reason="Goodwill credit",
        )
        assert c_entry.credit == Decimal("20.0000")
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("100.0000")

    def test_reconcile_customer_balance(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Reconcile Co")
        services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("300.0000"),
        )
        services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.PAYMENT,
            credit=Decimal("100.0000"),
        )
        # Manually alter current_balance field without transaction
        Customer.all_tenants.filter(pk=customer.pk).update(current_balance=Decimal("999.0000"))
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("999.0000")

        reconciled = services.reconcile_customer_balance(
            organization=org, customer=customer, auto_repair=True
        )
        assert reconciled["ledger_balance"] == Decimal("200.0000")
        assert reconciled["is_reconciled"] is False
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("200.0000")

    def test_balance_entry_immutability(self, org: Organization) -> None:
        customer = services.create_customer(organization=org, name="Immutable Co")
        entry = services.post_customer_transaction(
            organization=org,
            customer=customer,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("100.0000"),
        )

        with pytest.raises((RuntimeError, ValidationError)):
            entry.debit = Decimal("200.0000")
            entry.save()

        with pytest.raises((RuntimeError, ValidationError)):
            entry.delete()
