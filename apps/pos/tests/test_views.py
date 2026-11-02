"""View and HTMX integration tests for the Point of Sale (POS) module."""

import json
import subprocess
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.catalog.models import Product, ProductType, Unit
from apps.core.tenant_context import tenant_context
from apps.inventory import services as inventory_services
from apps.pos import selectors, services
from apps.pos.models import POSShiftStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, TaxCode, Warehouse

User = get_user_model()


@pytest.fixture
def pos_view_setup(db: None) -> dict[str, object]:
    org = Organization.objects.create(name="POS View Test Org", slug="pos-view-test-org")
    user = User.objects.create_user(email="cashier_view@example.com", password="password123")
    role = Role.objects.create(
        organization=org,
        name="POS Owner",
        permissions=["pos.access", "pos.checkout", "pos.manage", "pos.shift_open", "pos.shift_close"],
    )
    Membership.objects.create(organization=org, user=user, role=role, is_owner=True)

    branch = Branch.objects.create(organization=org, name="Downtown Branch", code="BR-DT")
    warehouse = Warehouse.objects.create(
        organization=org, name="Downtown Store", branch=branch, is_default=True
    )

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    unit = Unit.objects.create(organization=org, name="Piece", code="pcs")
    tax_code = TaxCode.objects.create(organization=org, code="VAT10", name="VAT 10%", rate=Decimal("10.00"))

    prod = Product.objects.create(
        organization=org,
        name="Latte Cup",
        sku="LATTE-01",
        type=ProductType.STOCK,
        selling_price=Decimal("4.0000"),
        cost_price=Decimal("1.5000"),
        unit=unit,
        tax_code=tax_code,
    )

    inventory_services.receive_stock(
        organization=org,
        warehouse=warehouse,
        product=prod,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("1.5000"),
        actor=user,
    )

    register = services.create_register(
        organization=org,
        name="Main Register",
        branch=branch,
        warehouse=warehouse,
        code="POS-01",
        actor=user,
    )

    client = Client()
    client.force_login(user)

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


def test_terminal_without_shift(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    response = client.get("/pos/")
    assert response.status_code == 200
    assert "pos/terminal_no_shift.html" in [t.name for t in response.templates]


def test_shift_open_flow_and_terminal(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    register = pos_view_setup["register"]  # type: ignore

    # Open shift via POST
    response = client.post(
        "/pos/shifts/open/",
        {
            "register": register.pk,
            "opening_cash": "50.00",
            "notes": "Morning open",
        },
    )
    assert response.status_code == 302
    assert response.url == "/pos/"

    # Now GET /pos/ should render terminal.html
    response = client.get("/pos/")
    assert response.status_code == 200
    assert "pos/terminal.html" in [t.name for t in response.templates]

    # HTMX search partial
    response_htmx = client.get(
        "/pos/?search=Latte",
        HTTP_HX_REQUEST="true",
    )
    assert response_htmx.status_code == 200
    assert "pos/partials/product_grid.html" in [t.name for t in response_htmx.templates]


def test_checkout_action_and_receipt(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    org = pos_view_setup["org"]  # type: ignore
    user = pos_view_setup["user"]  # type: ignore
    register = pos_view_setup["register"]  # type: ignore
    prod = pos_view_setup["prod"]  # type: ignore

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
                "unit_price": "4.0000",
                "discount_percent": "0.00",
                "tax_rate": "10.00",
            }
        ],
        "payments": [{"payment_method": "cash", "amount": "8.8000"}],
        "amount_tendered": "10.0000",
    }

    response = client.post(
        "/pos/checkout/",
        data=json.dumps(checkout_payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "receipt_url" in data

    # Check receipt view
    receipt_res = client.get(data["receipt_url"])
    assert receipt_res.status_code == 200
    assert "pos/receipt.html" in [t.name for t in receipt_res.templates]


def test_shift_close_flow(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    org = pos_view_setup["org"]  # type: ignore
    user = pos_view_setup["user"]  # type: ignore
    register = pos_view_setup["register"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("100.00"),
    )

    response = client.post(
        f"/pos/shifts/{shift.public_id}/close/",
        {
            "closing_cash_counted": "100.00",
            "notes": "Exact balance count",
        },
    )
    assert response.status_code == 302
    shift.refresh_from_db()
    assert shift.status == POSShiftStatus.CLOSED


def test_register_list_and_create(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    branch = pos_view_setup["branch"]  # type: ignore
    warehouse = pos_view_setup["warehouse"]  # type: ignore

    res = client.get("/pos/registers/")
    assert res.status_code == 200

    create_res = client.post(
        "/pos/registers/new/",
        {
            "name": "Drive-thru Terminal",
            "code": "POS-DRIVE",
            "branch": branch.pk,
            "warehouse": warehouse.pk,
            "is_active": True,
        },
    )
    assert create_res.status_code == 302
    assert create_res.url == "/pos/registers/"


def test_hold_and_resume_cart_views(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    org = pos_view_setup["org"]  # type: ignore
    user = pos_view_setup["user"]  # type: ignore
    register = pos_view_setup["register"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("100.00"),
    )

    hold_payload = {
        "shift_id": shift.pk,
        "cart_label": "Drive Thru Car 3",
        "total_amount": "15.0000",
        "cart_data": {"items": [{"id": 1, "qty": 1}]},
    }

    hold_res = client.post(
        "/pos/cart/hold/",
        data=json.dumps(hold_payload),
        content_type="application/json",
    )
    assert hold_res.status_code == 200
    held_id = hold_res.json()["held_cart_id"]

    resume_res = client.get(f"/pos/cart/{held_id}/resume/")
    assert resume_res.status_code == 200
    assert resume_res.json()["cart"]["cart_data"]["items"][0]["id"] == 1


def test_terminal_htmx_category_filter_returns_partial(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    org = pos_view_setup["org"]  # type: ignore
    user = pos_view_setup["user"]  # type: ignore
    register = pos_view_setup["register"]  # type: ignore

    services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("50.00"),
    )

    # HTMX request with category filter must return partial product grid, NOT full terminal.html
    res = client.get("/pos/?category=999", HTTP_HX_REQUEST="true")
    assert res.status_code == 200
    template_names = [t.name for t in res.templates]
    assert "pos/partials/product_grid.html" in template_names
    assert "pos/terminal.html" not in template_names


def test_checkout_insufficient_stock_returns_json_error(pos_view_setup: dict[str, object]) -> None:
    client: Client = pos_view_setup["client"]  # type: ignore
    org = pos_view_setup["org"]  # type: ignore
    user = pos_view_setup["user"]  # type: ignore
    prod = pos_view_setup["prod"]  # type: ignore
    register = pos_view_setup["register"]  # type: ignore

    shift = services.open_shift(
        organization=org,
        register=register,
        cashier=user,
        opening_cash=Decimal("50.00"),
    )

    # Attempt to purchase 999 units when only 50 are in stock
    payload = {
        "shift_id": shift.pk,
        "amount_tendered": "5000.0000",
        "lines": [
            {
                "product_id": prod.pk,
                "quantity": "999.0000",
                "unit_price": "4.0000",
                "discount_percent": "0.00",
                "tax_rate": "10.00",
            }
        ],
        "payments": [{"payment_method": "cash", "amount": "4395.6000"}],
    }

    res = client.post(
        "/pos/checkout/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_ACCEPT="application/json",
    )
    assert res.status_code == 400
    data = res.json()
    assert data["success"] is False
    assert "Cannot issue" in data["error"] or "stock" in data["error"].lower()


def test_printers_api_endpoint(client: Client, pos_view_setup: dict[str, object]) -> None:
    """Test live system printers endpoint."""
    user = pos_view_setup["user"]
    client.force_login(user)

    res = client.get("/pos/printers/")
    assert res.status_code == 200
    data = res.json()
    assert "printers" in data
    assert isinstance(data["printers"], list)


def test_get_system_printers_windows_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Windows printer parsing and virtual driver filtering."""

    fake_output = json.dumps([
        {
            "Name": "EPSON82A8C5 (L3250 Series)",
            "DriverName": "Microsoft IPP Class Driver",
            "PortName": "WSD-54f78017",
            "PrinterStatus": 3,
        },
        {
            "Name": "Thermal 80mm USB",
            "DriverName": "POS Receipt Driver",
            "PortName": "USB001",
            "PrinterStatus": 3,
        },
        {
            "Name": "Microsoft Print to PDF",
            "DriverName": "Microsoft Print To PDF",
            "PortName": "PORTPROMPT:",
            "PrinterStatus": 3,
        },
    ])

    class FakeCompletedProcess:
        returncode = 0
        stdout = fake_output

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompletedProcess())
    printers = selectors._get_windows_printers()

    assert len(printers) == 2
    assert printers[0]["id"] == "EPSON82A8C5 (L3250 Series)"
    assert printers[0]["type"] == "wifi"
    assert printers[0]["badge"] == "Wi-Fi"
    assert printers[1]["id"] == "Thermal 80mm USB"
    assert printers[1]["type"] == "usb"
    assert printers[1]["badge"] == "USB"
