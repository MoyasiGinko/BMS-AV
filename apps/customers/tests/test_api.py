"""Integration tests for customer REST API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.customers import services
from apps.customers.models import BalanceEntryType, Customer, CustomerType
from apps.tenancy.services import provision_organization


@pytest.fixture
def customer_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="cust_api_admin@example.com", password="Password123!")
    org = provision_organization(
        name="API Customer Org", slug="api-cust-org", owner=admin_user, plan="starter"
    )

    customer = services.create_customer(
        organization=org,
        name="Global Distribution Inc",
        code="CUST-GDI",
        type=CustomerType.BUSINESS,
        email="ap@gdi.example",
        phone="+1 555-4321",
        tax_id="US12345678",
        currency="USD",
        credit_limit=Decimal("15000.0000"),
        opening_balance=Decimal("1200.0000"),
    )

    client = APIClient()
    client.force_authenticate(user=admin_user)

    return {
        "client": client,
        "admin_user": admin_user,
        "org": org,
        "customer": customer,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
class TestCustomerAPI:
    def test_list_customers(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]

        resp = client.get("/api/v1/customers/accounts/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["results"]
        assert len(data) == 1
        assert data[0]["name"] == "Global Distribution Inc"
        assert Decimal(data[0]["current_balance"]) == Decimal("1200.0000")

    def test_create_customer(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        org = customer_api_setup["org"]

        payload = {
            "name": "Precision Optics Ltd",
            "type": "business",
            "email": "procurement@precision.example",
            "currency": "USD",
            "credit_limit": "8000.0000",
            "payment_terms_days": 30,
            "opening_balance": "450.0000",
        }
        resp = client.post("/api/v1/customers/accounts/", data=payload, format="json", **headers)
        assert resp.status_code == status.HTTP_201_CREATED
        res_data = resp.json()
        assert res_data["name"] == "Precision Optics Ltd"
        assert res_data["code"].startswith("CUST-")
        assert Decimal(res_data["current_balance"]) == Decimal("450.0000")

        # Verify DB entry
        assert Customer.all_tenants.filter(organization=org, name="Precision Optics Ltd").exists()

    def test_retrieve_customer_detail(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        resp = client.get(f"/api/v1/customers/accounts/{customer.public_id}/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["public_id"] == str(customer.public_id)
        assert data["name"] == "Global Distribution Inc"
        assert Decimal(data["credit_limit"]) == Decimal("15000.0000")

    def test_update_customer(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        resp = client.patch(
            f"/api/v1/customers/accounts/{customer.public_id}/",
            data={"credit_limit": "20000.0000", "notes": "Credit limit raised based on annual review"},
            format="json",
            **headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        customer.refresh_from_db()
        assert customer.credit_limit == Decimal("20000.0000")
        assert customer.notes == "Credit limit raised based on annual review"

    def test_customer_ledger_endpoint(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        resp = client.get(f"/api/v1/customers/accounts/{customer.public_id}/ledger/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()["results"]
        assert len(data) >= 1
        assert data[0]["entry_type"] == BalanceEntryType.OPENING_BALANCE
        assert Decimal(data[0]["balance_after"]) == Decimal("1200.0000")

    def test_customer_statement_endpoint(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        resp = client.get(f"/api/v1/customers/accounts/{customer.public_id}/statement/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "aging" in data
        assert "current" in data["aging"]
        assert "days_1_30" in data["aging"]
        assert "closing_balance" in data
        assert Decimal(data["closing_balance"]) == Decimal("1200.0000")

    def test_customer_adjust_balance_endpoint(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        payload = {
            "adjustment_type": "debit",
            "amount": "300.0000",
            "reference_number": "ADJ-API-01",
            "reason": "Freight surcharge adjustment",
        }
        resp = client.post(
            f"/api/v1/customers/accounts/{customer.public_id}/adjust-balance/",
            data=payload,
            format="json",
            **headers,
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert Decimal(data["balance_after"]) == Decimal("1500.0000")
        customer.refresh_from_db()
        assert customer.current_balance == Decimal("1500.0000")

    def test_address_viewset(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        payload = {
            "customer": str(customer.public_id),
            "type": "shipping",
            "recipient_name": "Warehouse Receiving",
            "line1": "500 Logistics Blvd",
            "city": "Chicago",
            "state_or_province": "IL",
            "postal_code": "60607",
            "country": "US",
            "is_default": True,
        }
        resp = client.post("/api/v1/customers/addresses/", data=payload, format="json", **headers)
        assert resp.status_code == status.HTTP_201_CREATED

        list_resp = client.get(f"/api/v1/customers/addresses/?customer={customer.public_id}", **headers)
        assert list_resp.status_code == status.HTTP_200_OK
        assert len(list_resp.json()["results"]) >= 1

    def test_contact_viewset(self, customer_api_setup: dict[str, Any]) -> None:
        client: APIClient = customer_api_setup["client"]
        headers: dict[str, str] = customer_api_setup["headers"]
        customer: Customer = customer_api_setup["customer"]

        payload = {
            "customer": str(customer.public_id),
            "first_name": "Elena",
            "last_name": "Rostova",
            "title": "Director of Supply Chain",
            "email": "elena@gdi.example",
            "phone": "+1 555-8888",
            "is_primary": True,
        }
        resp = client.post("/api/v1/customers/contacts/", data=payload, format="json", **headers)
        assert resp.status_code == status.HTTP_201_CREATED

        list_resp = client.get(f"/api/v1/customers/contacts/?customer={customer.public_id}", **headers)
        assert list_resp.status_code == status.HTTP_200_OK
        assert len(list_resp.json()["results"]) >= 1
