"""Integration tests for customer web views and HTMX interactions."""

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.customers import services
from apps.customers.models import (
    AddressType,
    Customer,
    CustomerAddress,
    CustomerContact,
    CustomerStatus,
    CustomerType,
)
from apps.tenancy.models import Membership, Organization, Role


@pytest.fixture
def view_setup(db: None) -> dict[str, Any]:
    user = User.objects.create_user(email="cust_admin@example.com", password="Password123!")
    org = Organization.objects.create(name="Customer Web Org", slug="cust-web-org")

    role = Role.objects.create(
        organization=org,
        name="Customer Manager",
        permissions=[
            "customers.view",
            "customers.create",
            "customers.update",
            "customers.delete",
            "customers.adjust_balance",
            "customers.export",
        ],
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    client = Client()
    client.force_login(user)

    customer = services.create_customer(
        organization=org,
        name="Acme Industrial",
        code="CUST-0001",
        type=CustomerType.BUSINESS,
        status=CustomerStatus.ACTIVE,
        credit_limit=Decimal("5000.0000"),
        opening_balance=Decimal("250.0000"),
    )

    return {
        "user": user,
        "org": org,
        "client": client,
        "customer": customer,
    }


@pytest.mark.django_db
class TestCustomerViews:
    def test_customer_list_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        url = reverse("customers:customer_list")
        response = client.get(url)
        assert response.status_code == 200
        assert "Acme Industrial" in response.content.decode()

    def test_customer_list_htmx_partial(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        url = reverse("customers:customer_list")
        response = client.get(url, HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        content = response.content.decode()
        assert "Acme Industrial" in content
        # HTMX partial returns only the table container, not full base layout
        assert "<html" not in content

    def test_customer_create_get(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        url = reverse("customers:customer_create")
        response = client.get(url)
        assert response.status_code == 200
        assert "New Customer" in response.content.decode() or "Create Customer" in response.content.decode()

    def test_customer_create_post(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        org: Organization = view_setup["org"]
        url = reverse("customers:customer_create")
        payload = {
            "name": "Global Logistics Corp",
            "code": "CUST-GLC",
            "type": CustomerType.BUSINESS,
            "status": CustomerStatus.ACTIVE,
            "email": "info@glc.example",
            "phone": "+1 555-9000",
            "tax_id": "TAX99999",
            "currency": "USD",
            "credit_limit": "10000.0000",
            "payment_terms_days": 30,
            "opening_balance": "500.0000",
        }
        response = client.post(url, data=payload)
        assert response.status_code in (302, 200)

        created = Customer.all_tenants.filter(organization=org, code="CUST-GLC").first()
        assert created is not None
        assert created.name == "Global Logistics Corp"
        assert created.current_balance == Decimal("500.0000")

    def test_customer_detail_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        customer: Customer = view_setup["customer"]
        url = reverse("customers:customer_detail", kwargs={"customer_id": customer.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert customer.name in response.content.decode()

    def test_customer_update_view(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        customer: Customer = view_setup["customer"]
        url = reverse("customers:customer_update", kwargs={"customer_id": customer.pk})

        # GET
        get_resp = client.get(url)
        assert get_resp.status_code == 200

        # POST
        payload = {
            "name": "Acme Industrial Updated",
            "code": customer.code,
            "type": customer.type,
            "status": CustomerStatus.ACTIVE,
            "email": "updated@acme.example",
            "currency": "USD",
            "credit_limit": "7500.0000",
            "payment_terms_days": 45,
        }
        post_resp = client.post(url, data=payload)
        assert post_resp.status_code in (302, 200)
        customer.refresh_from_db()
        assert customer.name == "Acme Industrial Updated"
        assert customer.credit_limit == Decimal("7500.0000")

    def test_customer_adjust_balance(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        customer: Customer = view_setup["customer"]
        url = reverse("customers:customer_adjust_balance", kwargs={"customer_id": customer.pk})

        get_resp = client.get(url)
        assert get_resp.status_code == 302

        post_resp = client.post(
            url,
            data={
                "adjustment_type": "debit",
                "amount": "100.0000",
                "reference_number": "ADJ-TEST-1",
                "reason": "Late fee testing",
            },
        )
        assert post_resp.status_code in (302, 200)
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("350.0000")

    def test_customer_address_and_contact_create(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        customer: Customer = view_setup["customer"]

        # Address
        addr_url = reverse("customers:customer_address_create", kwargs={"customer_id": customer.pk})
        addr_resp = client.post(
            addr_url,
            data={
                "type": AddressType.BILLING,
                "recipient_name": "Billing Dept",
                "line1": "789 Pine St",
                "city": "Seattle",
                "state_or_province": "WA",
                "postal_code": "98101",
                "country": "US",
                "is_default": True,
            },
        )
        assert addr_resp.status_code in (302, 200)
        assert CustomerAddress.all_tenants.filter(customer=customer, city="Seattle").exists()

        # Contact
        contact_url = reverse("customers:customer_contact_create", kwargs={"customer_id": customer.pk})
        contact_resp = client.post(
            contact_url,
            data={
                "first_name": "Sarah",
                "last_name": "Connor",
                "title": "CFO",
                "email": "sarah@acme.example",
                "phone": "+1 555-7788",
                "is_primary": True,
            },
        )
        assert contact_resp.status_code in (302, 200)
        assert CustomerContact.all_tenants.filter(customer=customer, first_name="Sarah").exists()

    def test_customer_statement_print(self, view_setup: dict[str, Any]) -> None:
        client: Client = view_setup["client"]
        customer: Customer = view_setup["customer"]
        url = reverse("customers:customer_statement_print", kwargs={"customer_id": customer.pk})
        response = client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert customer.name in content
        assert "Accounts Receivable Statement" in content
