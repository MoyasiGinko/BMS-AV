"""REST API tests for the Point of Sale (POS) module."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services as inventory_services
from apps.pos import services
from apps.pos.models import POSShiftStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def pos_api_setup(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="POS API Org", slug="pos-api-org")
    user = User.objects.create_user(email="api_cashier@example.com", password="Password123!")

    # Role with full pos permissions
    role = Role.objects.create(
        organization=org,
        name="POS Admin",
        permissions=["pos.access", "pos.manage", "pos.checkout", "pos.shift_open", "pos.shift_close"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)

    branch = Branch.objects.create(organization=org, name="Central Branch", code="BR-API")
    warehouse = Warehouse.objects.create(
        organization=org, name="Central Store", branch=branch, is_default=True
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00"))

    prod = Product.objects.create(
        organization=org,
        name="Pastry Croissant",
        sku="CROISSANT-01",
        type=ProductType.STOCK,
        selling_price=Decimal("3.5000"),
        cost_price=Decimal("1.0000"),
        unit=unit,
        tax_code=tax_code,
    )

    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod,
        quantity=Decimal("100.0000"),
        unit_cost=Decimal("1.0000"),
        actor=user,
    )

    register = services.create_register(
        organization=org,
        name="API Terminal",
        branch=branch,
        warehouse=warehouse,
        code="POS-API",
        actor=user,
    )

    client = APIClient()
    client.force_authenticate(user=user)
    # Set active organization header
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.id)

    with tenant_context(org):
        yield {
            "org": org,
            "user": user,
            "branch": branch,
            "warehouse": warehouse,
            "prod": prod,
            "register": register,
            "client": client,
        }


def test_api_registers_crud(pos_api_setup: dict[str, object]) -> None:
    client: APIClient = pos_api_setup["client"]  # type: ignore
    branch = pos_api_setup["branch"]  # type: ignore
    warehouse = pos_api_setup["warehouse"]  # type: ignore

    # List
    res = client.get("/api/v1/pos/registers/")
    assert res.status_code == status.HTTP_200_OK

    # Create
    create_res = client.post(
        "/api/v1/pos/registers/",
        {
            "name": "Register 2",
            "code": "POS-02",
            "branch": branch.pk,
            "warehouse": warehouse.pk,
            "is_active": True,
        },
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    assert create_res.data["code"] == "POS-02"


def test_api_shifts_lifecycle(pos_api_setup: dict[str, object]) -> None:
    client: APIClient = pos_api_setup["client"]  # type: ignore
    register = pos_api_setup["register"]  # type: ignore

    # No active shift
    active_res = client.get("/api/v1/pos/shifts/active/")
    assert active_res.status_code == status.HTTP_404_NOT_FOUND

    # Open shift
    open_res = client.post(
        "/api/v1/pos/shifts/open/",
        {
            "register": register.pk,
            "opening_cash": "75.0000",
            "notes": "API open test",
        },
    )
    assert open_res.status_code == status.HTTP_201_CREATED
    shift_id = open_res.data["public_id"]
    assert open_res.data["status"] == POSShiftStatus.OPEN

    # Now active shift is found
    active_res = client.get("/api/v1/pos/shifts/active/")
    assert active_res.status_code == status.HTTP_200_OK
    assert active_res.data["public_id"] == shift_id

    # Close shift
    close_res = client.post(
        f"/api/v1/pos/shifts/{shift_id}/close/",
        {
            "closing_cash_counted": "75.0000",
            "notes": "Exact count",
        },
    )
    assert close_res.status_code == status.HTTP_200_OK
    assert close_res.data["status"] == POSShiftStatus.CLOSED


def test_api_pos_checkout(pos_api_setup: dict[str, object]) -> None:
    client: APIClient = pos_api_setup["client"]  # type: ignore
    org = pos_api_setup["org"]  # type: ignore
    user = pos_api_setup["user"]  # type: ignore
    register = pos_api_setup["register"]  # type: ignore
    prod = pos_api_setup["prod"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("50.00"),
    )

    checkout_payload = {
        "shift_id": shift.pk,
        "lines": [
            {
                "product_id": prod.pk,
                "quantity": "2.0000",
                "unit_price": "3.5000",
                "discount_percent": "0.00",
                "tax_rate": "10.00",
            }
        ],
        "payments": [{"payment_method": "cash", "amount": "7.7000"}],
        "amount_tendered": "10.0000",
    }

    res = client.post("/api/v1/pos/sales/checkout/", data=checkout_payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    assert Decimal(str(res.data["total_amount"])) == Decimal("7.7000")
    assert Decimal(str(res.data["change_given"])) == Decimal("2.3000")
    assert res.data["receipt_number"].startswith("REC-")
