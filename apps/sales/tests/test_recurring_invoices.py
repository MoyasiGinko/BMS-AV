"""Tests for Recurring Invoices: scheduling, generation, ledger posting, and API endpoints."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting import services as accounting_services
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.catalog.models import Product, ProductType, Unit
from apps.core.notifications import get_email_adapter
from apps.core.tenant_context import tenant_context
from apps.customers import services as customers_services
from apps.inventory import services as inventory_services
from apps.sales import services
from apps.sales.exceptions import RecurringProfileError
from apps.sales.models import (
    InvoiceStatus,
    RecurringFrequency,
    RecurringProfileStatus,
)
from apps.tenancy.models import TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def recurring_setup(db: None) -> dict[str, Any]:
    """Seed test tenants, accounting, products, and customers."""
    seed_default_plans()

    admin_user = User.objects.create_user(email="rec_admin@example.com", password="Password123!")
    org_a = provision_organization(
        name="Recurring Org A",
        slug="recurring-org-a",
        owner=admin_user,
        plan="starter",
    )

    accounting_services.seed_chart_of_accounts(organization=org_a)
    accounting_services.seed_fiscal_calendar(organization=org_a)

    wh_a = Warehouse.all_tenants.get(organization=org_a, is_default=True)
    unit_a = Unit.all_tenants.filter(organization=org_a, code="pcs").first()
    if unit_a is None:
        unit_a = Unit.objects.create(organization=org_a, name="Piece", code="pcs")
    tax_a = TaxCode.all_tenants.filter(organization=org_a, code="VAT10").first()
    if tax_a is None:
        tax_a = TaxCode.objects.create(
            organization=org_a, code="VAT10", name="VAT 10%", rate=Decimal("10.00")
        )

    product_stock = Product.objects.create(
        organization=org_a,
        name="SaaS Hardware Appliance",
        sku="SHA-01",
        type=ProductType.STOCK,
        selling_price=Decimal("200.0000"),
        cost_price=Decimal("80.0000"),
        unit=unit_a,
        tax_code=tax_a,
    )
    product_service = Product.objects.create(
        organization=org_a,
        name="Monthly SaaS Subscription",
        sku="SAAS-SUB",
        type=ProductType.SERVICE,
        selling_price=Decimal("50.0000"),
        cost_price=Decimal("0.0000"),
        unit=unit_a,
        tax_code=tax_a,
    )

    inventory_services.receive_stock(
        organization=org_a,
        warehouse=wh_a,
        product=product_stock,
        quantity=Decimal("50.0000"),
        unit_cost=Decimal("80.0000"),
    )

    customer_a = customers_services.create_customer(
        organization=org_a,
        name="Acme Corporation",
        email="billing@acmecorp.com",
        credit_limit=Decimal("50000.0000"),
        payment_terms_days=15,
    )

    # Second tenant for isolation checks
    other_user = User.objects.create_user(email="rec_other@example.com", password="Password123!")
    org_b = provision_organization(
        name="Recurring Org B",
        slug="recurring-org-b",
        owner=other_user,
        plan="starter",
    )
    customer_b = customers_services.create_customer(
        organization=org_b,
        name="Globex Inc",
        email="accounts@globex.com",
        credit_limit=Decimal("10000.0000"),
    )

    client = APIClient()
    client.force_authenticate(user=admin_user)

    with tenant_context(org_a):
        yield {
            "client": client,
            "admin_user": admin_user,
            "other_user": other_user,
            "org_a": org_a,
            "org_b": org_b,
            "wh_a": wh_a,
            "product_stock": product_stock,
            "product_service": product_service,
            "customer_a": customer_a,
            "customer_b": customer_b,
        }


def test_advance_recurring_date_calculation():
    """Verify schedule date arithmetic across various frequencies and leap years."""
    # Daily
    d1 = datetime.date(2026, 3, 1)
    res_daily = services.advance_recurring_date(d1, RecurringFrequency.DAILY, interval=3)
    assert res_daily == datetime.date(2026, 3, 4)

    # Weekly
    res_weekly = services.advance_recurring_date(d1, RecurringFrequency.WEEKLY, interval=2)
    assert res_weekly == datetime.date(2026, 3, 15)

    # Biweekly
    res_biweekly = services.advance_recurring_date(d1, RecurringFrequency.BIWEEKLY, interval=1)
    assert res_biweekly == datetime.date(2026, 3, 15)

    # Monthly regular
    res_monthly = services.advance_recurring_date(d1, RecurringFrequency.MONTHLY, interval=1)
    assert res_monthly == datetime.date(2026, 4, 1)

    # Monthly with month-end clipping: Jan 31 -> Feb 28 in non-leap year (2025)
    d_jan31 = datetime.date(2025, 1, 31)
    res_jan = services.advance_recurring_date(d_jan31, RecurringFrequency.MONTHLY, interval=1)
    assert res_jan == datetime.date(2025, 2, 28)

    # Leap year month-end clipping: Jan 31, 2024 -> Feb 29, 2024
    d_jan31_leap = datetime.date(2024, 1, 31)
    res_leap = services.advance_recurring_date(d_jan31_leap, RecurringFrequency.MONTHLY, interval=1)
    assert res_leap == datetime.date(2024, 2, 29)

    # Quarterly
    res_qtr = services.advance_recurring_date(d1, RecurringFrequency.QUARTERLY, interval=1)
    assert res_qtr == datetime.date(2026, 6, 1)

    # Semi-annually / Biannual
    res_semi = services.advance_recurring_date(d1, RecurringFrequency.BIANNUAL, interval=1)
    assert res_semi == datetime.date(2026, 9, 1)

    # Annually from Feb 29 in leap year
    d_leap = datetime.date(2024, 2, 29)
    res_ann = services.advance_recurring_date(d_leap, RecurringFrequency.ANNUAL, interval=1)
    assert res_ann == datetime.date(2025, 2, 28)


def test_create_recurring_profile(recurring_setup: dict[str, Any]):
    """Ensure creating a recurring profile persists line items and initializes schedule."""
    org = recurring_setup["org_a"]
    user = recurring_setup["admin_user"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]
    prod_service = recurring_setup["product_service"]

    profile = services.create_recurring_profile(
        organization=org,
        title="Monthly Hosting & Support",
        customer=customer,
        warehouse=wh,
        frequency=RecurringFrequency.MONTHLY,
        interval=1,
        start_date=datetime.date(2026, 5, 1),
        payment_terms_days=30,
        currency="USD",
        auto_post=True,
        send_email=True,
        total_cycles_limit=12,
        lines=[
            {
                "product_id": prod_service.pk,
                "description": "Premium Cloud Server",
                "quantity": Decimal("2.0000"),
                "unit_price": Decimal("50.0000"),
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("10.00"),
            }
        ],
        actor=user,
    )

    assert profile.pk is not None
    assert profile.status == RecurringProfileStatus.ACTIVE
    assert profile.next_issue_date == datetime.date(2026, 5, 1)
    assert profile.cycles_completed == 0
    assert profile.lines.count() == 1

    line = profile.lines.first()
    assert line.product == prod_service
    assert line.quantity == Decimal("2.0000")


def test_create_recurring_profile_requires_lines(recurring_setup: dict[str, Any]):
    """Profiles without line items must raise a validation error."""
    org = recurring_setup["org_a"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]

    with pytest.raises(RecurringProfileError, match="at least one line item"):
        services.create_recurring_profile(
            organization=org,
            title="Empty Profile",
            customer=customer,
            warehouse=wh,
            lines=[],
        )


def test_generate_single_recurring_invoice_auto_post(recurring_setup: dict[str, Any]):
    """Auto-post recurring invoices should post the invoice, update stock, AR, and trigger email."""
    org = recurring_setup["org_a"]
    user = recurring_setup["admin_user"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]
    prod_stock = recurring_setup["product_stock"]

    fake_adapter = get_email_adapter()
    fake_adapter.clear()

    profile = services.create_recurring_profile(
        organization=org,
        title="Quarterly Appliance Refresh",
        customer=customer,
        warehouse=wh,
        frequency=RecurringFrequency.QUARTERLY,
        interval=1,
        start_date=datetime.date(2026, 1, 1),
        auto_post=True,
        send_email=True,
        total_cycles_limit=4,
        lines=[
            {
                "product_id": prod_stock.pk,
                "description": "Hardware Box",
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("200.0000"),
                "discount_percent": Decimal("0.00"),
                "tax_rate": Decimal("10.00"),
            }
        ],
        actor=user,
    )

    invoice = services.generate_single_recurring_invoice(
        organization=org,
        profile=profile,
        actor=user,
    )

    assert invoice.status == InvoiceStatus.POSTED
    assert invoice.recurring_profile == profile
    assert invoice.customer == customer
    assert invoice.grand_total == Decimal("220.0000")  # 200 + 10% tax

    # Profile cycle and dates advanced
    profile.refresh_from_db()
    assert profile.cycles_completed == 1
    assert profile.last_issue_date == datetime.date(2026, 1, 1)
    assert profile.next_issue_date == datetime.date(2026, 4, 1)
    assert profile.status == RecurringProfileStatus.ACTIVE

    # Customer balance updated
    customer.refresh_from_db()
    assert customer.current_balance == Decimal("220.0000")

    # Email was dispatched
    assert len(fake_adapter.outbox) == 1
    sent_email = fake_adapter.outbox[0]
    assert customer.email in sent_email.to
    assert invoice.invoice_number in sent_email.subject


def test_generate_recurring_invoice_draft_mode(recurring_setup: dict[str, Any]):
    """When auto_post is False, generated invoice remains DRAFT and no stock is released yet."""
    org = recurring_setup["org_a"]
    user = recurring_setup["admin_user"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]
    prod_service = recurring_setup["product_service"]

    profile = services.create_recurring_profile(
        organization=org,
        title="Draft Only Subscription",
        customer=customer,
        warehouse=wh,
        frequency=RecurringFrequency.MONTHLY,
        interval=1,
        start_date=datetime.date(2026, 6, 1),
        auto_post=False,
        send_email=False,
        lines=[
            {
                "product_id": prod_service.pk,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("50.0000"),
            }
        ],
        actor=user,
    )

    invoice = services.generate_single_recurring_invoice(
        organization=org,
        profile=profile,
        actor=user,
    )

    assert invoice.status == InvoiceStatus.DRAFT
    assert invoice.recurring_profile == profile
    profile.refresh_from_db()
    assert profile.cycles_completed == 1
    assert profile.next_issue_date == datetime.date(2026, 7, 1)


def test_recurring_profile_limit_expiry(recurring_setup: dict[str, Any]):
    """Profile status should become EXPIRED when cycles reach total_cycles_limit."""
    org = recurring_setup["org_a"]
    user = recurring_setup["admin_user"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]
    prod_service = recurring_setup["product_service"]

    profile = services.create_recurring_profile(
        organization=org,
        title="2-Cycle Trial",
        customer=customer,
        warehouse=wh,
        frequency=RecurringFrequency.MONTHLY,
        interval=1,
        start_date=datetime.date(2026, 1, 1),
        auto_post=True,
        send_email=False,
        total_cycles_limit=2,
        lines=[
            {
                "product_id": prod_service.pk,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("50.0000"),
            }
        ],
        actor=user,
    )

    # 1st run
    services.generate_single_recurring_invoice(organization=org, profile=profile, actor=user)
    profile.refresh_from_db()
    assert profile.status == RecurringProfileStatus.ACTIVE
    assert profile.cycles_completed == 1

    # 2nd run
    services.generate_single_recurring_invoice(organization=org, profile=profile, actor=user)
    profile.refresh_from_db()
    assert profile.status == RecurringProfileStatus.EXPIRED
    assert profile.cycles_completed == 2

    # Attempting a 3rd run should fail
    with pytest.raises(RecurringProfileError, match="status is expired"):
        services.generate_single_recurring_invoice(organization=org, profile=profile, actor=user)


def test_pause_resume_cancel_profile(recurring_setup: dict[str, Any]):
    """Test pause, resume, and cancel lifecycle transitions."""
    org = recurring_setup["org_a"]
    user = recurring_setup["admin_user"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]
    prod_service = recurring_setup["product_service"]

    profile = services.create_recurring_profile(
        organization=org,
        title="Flexible Profile",
        customer=customer,
        warehouse=wh,
        frequency=RecurringFrequency.MONTHLY,
        lines=[
            {
                "product_id": prod_service.pk,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("50.0000"),
            }
        ],
        actor=user,
    )

    # Pause
    paused = services.pause_recurring_profile(organization=org, profile=profile, actor=user)
    assert paused.status == RecurringProfileStatus.PAUSED

    # Paused cannot be generated
    with pytest.raises(RecurringProfileError, match="status is paused"):
        services.generate_single_recurring_invoice(organization=org, profile=paused, actor=user)

    # Resume
    resumed = services.resume_recurring_profile(organization=org, profile=paused, actor=user)
    assert resumed.status == RecurringProfileStatus.ACTIVE

    # Cancel
    cancelled = services.cancel_recurring_profile(organization=org, profile=resumed, actor=user)
    assert cancelled.status == RecurringProfileStatus.CANCELLED

    # Cancelled cannot be resumed
    with pytest.raises(RecurringProfileError, match="Cannot resume cancelled"):
        services.resume_recurring_profile(organization=org, profile=cancelled, actor=user)


def test_process_due_recurring_invoices_batch(recurring_setup: dict[str, Any]):
    """The batch generator should process only active profiles with next_issue_date <= as_of_date."""
    org = recurring_setup["org_a"]
    wh = recurring_setup["wh_a"]
    customer = recurring_setup["customer_a"]
    prod_service = recurring_setup["product_service"]

    today = datetime.date(2026, 6, 1)

    # Profile 1: Due today -> should generate
    p1 = services.create_recurring_profile(
        organization=org,
        title="Profile 1 Due",
        customer=customer,
        warehouse=wh,
        start_date=today,
        lines=[
            {
                "product_id": prod_service.pk,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("10.0000"),
            }
        ],
    )

    # Profile 2: Due in future -> should NOT generate
    p2 = services.create_recurring_profile(
        organization=org,
        title="Profile 2 Future",
        customer=customer,
        warehouse=wh,
        start_date=datetime.date(2026, 6, 15),
        lines=[
            {
                "product_id": prod_service.pk,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("20.0000"),
            }
        ],
    )

    # Profile 3: Due today but paused -> should NOT generate
    p3 = services.create_recurring_profile(
        organization=org,
        title="Profile 3 Paused",
        customer=customer,
        warehouse=wh,
        start_date=today,
        lines=[
            {
                "product_id": prod_service.pk,
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal("30.0000"),
            }
        ],
    )
    services.pause_recurring_profile(organization=org, profile=p3)

    results = services.generate_due_recurring_invoices(organization=org, as_of_date=today)
    assert len(results["generated"]) == 1
    assert results["generated"][0]["profile_id"] == p1.pk

    p1.refresh_from_db()
    assert p1.cycles_completed == 1
    assert p1.next_issue_date == datetime.date(2026, 7, 1)

    p2.refresh_from_db()
    assert p2.cycles_completed == 0

    p3.refresh_from_db()
    assert p3.cycles_completed == 0


def test_recurring_invoice_api_crud_and_actions(recurring_setup: dict[str, Any]):
    """Test REST API endpoints for recurring invoice profiles."""
    client = recurring_setup["client"]
    customer = recurring_setup["customer_a"]
    wh = recurring_setup["wh_a"]
    prod = recurring_setup["product_service"]

    payload = {
        "title": "API Managed Subscription",
        "customer": customer.pk,
        "warehouse": wh.pk,
        "frequency": "monthly",
        "interval": 1,
        "start_date": "2026-04-01",
        "payment_terms_days": 30,
        "currency": "USD",
        "auto_post": True,
        "send_email": False,
        "total_cycles_limit": 6,
        "lines": [
            {
                "product": prod.pk,
                "description": "Standard license",
                "quantity": "5.0000",
                "unit_price": "20.0000",
                "tax_rate": "10.00",
            }
        ],
    }

    # Create
    response = client.post("/api/v1/sales/recurring-invoices/", payload, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.data
    profile_public_id = response.data["public_id"]
    assert response.data["title"] == "API Managed Subscription"
    assert response.data["status"] == "active"
    assert len(response.data["lines"]) == 1

    # Retrieve
    get_res = client.get(f"/api/v1/sales/recurring-invoices/{profile_public_id}/")
    assert get_res.status_code == status.HTTP_200_OK

    # Pause action
    pause_res = client.post(f"/api/v1/sales/recurring-invoices/{profile_public_id}/pause/")
    assert pause_res.status_code == status.HTTP_200_OK
    assert pause_res.data["status"] == "paused"

    # Resume action
    resume_res = client.post(f"/api/v1/sales/recurring-invoices/{profile_public_id}/resume/")
    assert resume_res.status_code == status.HTTP_200_OK
    assert resume_res.data["status"] == "active"

    # Generate Now action
    gen_res = client.post(f"/api/v1/sales/recurring-invoices/{profile_public_id}/generate_now/")
    assert gen_res.status_code == status.HTTP_201_CREATED
    assert "invoice_number" in gen_res.data
    assert gen_res.data["status"] == "posted"

    # Cross-tenant isolation
    other_client = APIClient()
    other_client.force_authenticate(user=recurring_setup["other_user"])
    iso_res = other_client.get(f"/api/v1/sales/recurring-invoices/{profile_public_id}/")
    assert iso_res.status_code == status.HTTP_404_NOT_FOUND
