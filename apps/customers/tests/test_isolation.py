"""Multi-tenant isolation and data leakage prevention tests for customers."""

from decimal import Decimal

import pytest

from apps.core.tenant_context import tenant_context
from apps.customers import selectors, services
from apps.customers.models import (
    AddressType,
    BalanceEntryType,
    Customer,
    CustomerAddress,
    CustomerBalanceEntry,
    CustomerContact,
)
from apps.tenancy.models import Organization


@pytest.fixture
def org_one() -> Organization:
    return Organization.objects.create(name="Tenant One Corp", slug="tenant-one-corp")


@pytest.fixture
def org_two() -> Organization:
    return Organization.objects.create(name="Tenant Two Corp", slug="tenant-two-corp")


@pytest.fixture
def cust_one(org_one: Organization) -> Customer:
    return services.create_customer(
        organization=org_one,
        name="Customer One",
        code="CUST-ONE",
        opening_balance=Decimal("500.0000"),
    )


@pytest.fixture
def cust_two(org_two: Organization) -> Customer:
    return services.create_customer(
        organization=org_two,
        name="Customer Two",
        code="CUST-TWO",
        opening_balance=Decimal("750.0000"),
    )


@pytest.mark.django_db
class TestCustomerTenantIsolation:
    def test_customer_scoped_querysets(
        self,
        org_one: Organization,
        org_two: Organization,
        cust_one: Customer,
        cust_two: Customer,
    ) -> None:
        with tenant_context(org_one):
            qs_one = Customer.objects.all()
            assert qs_one.count() == 1
            assert qs_one.first() == cust_one
            assert not qs_one.filter(pk=cust_two.pk).exists()

        with tenant_context(org_two):
            qs_two = Customer.objects.all()
            assert qs_two.count() == 1
            assert qs_two.first() == cust_two
            assert not qs_two.filter(pk=cust_one.pk).exists()

    def test_customer_addresses_scoped(
        self,
        org_one: Organization,
        org_two: Organization,
        cust_one: Customer,
        cust_two: Customer,
    ) -> None:
        addr_one = services.add_customer_address(
            organization=org_one,
            customer=cust_one,
            type=AddressType.SHIPPING,
            line1="100 First Way",
            city="Metropolis",
            country="US",
        )
        addr_two = services.add_customer_address(
            organization=org_two,
            customer=cust_two,
            type=AddressType.SHIPPING,
            line1="200 Second Way",
            city="Gotham",
            country="US",
        )

        with tenant_context(org_one):
            assert CustomerAddress.objects.filter(pk=addr_one.pk).exists()
            assert not CustomerAddress.objects.filter(pk=addr_two.pk).exists()

        with tenant_context(org_two):
            assert CustomerAddress.objects.filter(pk=addr_two.pk).exists()
            assert not CustomerAddress.objects.filter(pk=addr_one.pk).exists()

    def test_customer_contacts_scoped(
        self,
        org_one: Organization,
        org_two: Organization,
        cust_one: Customer,
        cust_two: Customer,
    ) -> None:
        c_one = services.add_customer_contact(
            organization=org_one,
            customer=cust_one,
            first_name="Alice",
            last_name="Org1",
        )
        c_two = services.add_customer_contact(
            organization=org_two,
            customer=cust_two,
            first_name="Bob",
            last_name="Org2",
        )

        with tenant_context(org_one):
            assert CustomerContact.objects.filter(pk=c_one.pk).exists()
            assert not CustomerContact.objects.filter(pk=c_two.pk).exists()

        with tenant_context(org_two):
            assert CustomerContact.objects.filter(pk=c_two.pk).exists()
            assert not CustomerContact.objects.filter(pk=c_one.pk).exists()

    def test_customer_ledger_scoped(
        self,
        org_one: Organization,
        org_two: Organization,
        cust_one: Customer,
        cust_two: Customer,
    ) -> None:
        e_one = services.post_customer_transaction(
            organization=org_one,
            customer=cust_one,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("100.0000"),
        )
        e_two = services.post_customer_transaction(
            organization=org_two,
            customer=cust_two,
            entry_type=BalanceEntryType.INVOICE,
            debit=Decimal("200.0000"),
        )

        with tenant_context(org_one):
            assert CustomerBalanceEntry.objects.filter(pk=e_one.pk).exists()
            assert not CustomerBalanceEntry.objects.filter(pk=e_two.pk).exists()

        with tenant_context(org_two):
            assert CustomerBalanceEntry.objects.filter(pk=e_two.pk).exists()
            assert not CustomerBalanceEntry.objects.filter(pk=e_one.pk).exists()

    def test_selector_cross_tenant_access_denied(
        self,
        org_one: Organization,
        org_two: Organization,
        cust_one: Customer,
    ) -> None:
        assert (
            selectors.get_customer_by_id(
                organization=org_two,
                customer_id=cust_one.pk,
            )
            is None
        )

        assert (
            selectors.get_customer_by_public_id(
                organization=org_two,
                public_id=cust_one.public_id,
            )
            is None
        )
