"""Tests for Payment Reminders: rules engine, timing calculations, duplicate suppression, and API."""

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
from apps.sales import services
from apps.sales.exceptions import PaymentReminderError
from apps.sales.models import (
    PaymentReminderLog,
    PaymentReminderRule,
)
from apps.tenancy.models import NotificationPreference, TaxCode, Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def reminder_setup(db: None) -> dict[str, Any]:
    """Seed test tenants, accounting, products, and customers."""
    seed_default_plans()

    admin_user = User.objects.create_user(email="rem_admin@example.com", password="Password123!")
    org_a = provision_organization(
        name="Reminder Org A",
        slug="reminder-org-a",
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

    product = Product.objects.create(
        organization=org_a,
        name="Consulting Hours",
        sku="CONS-01",
        type=ProductType.SERVICE,
        selling_price=Decimal("100.0000"),
        unit=unit_a,
        tax_code=tax_a,
    )

    customer_a = customers_services.create_customer(
        organization=org_a,
        name="Omni Consumer Products",
        email="ap@omnicorp.example.com",
        credit_limit=Decimal("50000.0000"),
        payment_terms_days=30,
    )

    customer_no_email = customers_services.create_customer(
        organization=org_a,
        name="Offline Client",
        email="",
        credit_limit=Decimal("50000.0000"),
        payment_terms_days=30,
    )

    # Tenant B for isolation checks
    other_user = User.objects.create_user(email="rem_other@example.com", password="Password123!")
    org_b = provision_organization(
        name="Reminder Org B",
        slug="reminder-org-b",
        owner=other_user,
        plan="starter",
    )
    customer_b = customers_services.create_customer(
        organization=org_b,
        name="Initech",
        email="peter@initech.example.com",
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
            "product": product,
            "customer_a": customer_a,
            "customer_no_email": customer_no_email,
            "customer_b": customer_b,
        }


def test_create_and_manage_reminder_rules(reminder_setup: dict[str, Any]):
    """Test creating, updating, and duplicate constraints on reminder rules."""
    org = reminder_setup["org_a"]
    user = reminder_setup["admin_user"]

    rule = services.create_payment_reminder_rule(
        organization=org,
        name="3 Days Before Due",
        timing_days=-3,
        is_active=True,
        subject_template="Upcoming Due: {{ invoice_number }}",
        body_template=(
            "Dear {{ customer_name }}, your invoice {{ invoice_number }} of "
            "{{ currency }} {{ balance_due }} is due on {{ due_date }}."
        ),
        actor=user,
    )

    assert rule.pk is not None
    assert rule.timing_days == -3
    assert rule.is_active is True

    # Duplicate timing_days for the same organization must fail
    with pytest.raises(PaymentReminderError, match="timing_days=-3 already exists"):
        services.create_payment_reminder_rule(
            organization=org,
            name="Another 3 Days Rule",
            timing_days=-3,
            actor=user,
        )

    # Updating rule
    updated = services.update_payment_reminder_rule(
        organization=org,
        rule=rule,
        name="Upcoming Reminder (3d)",
        actor=user,
    )
    assert updated.name == "Upcoming Reminder (3d)"

    # Deleting rule
    services.delete_payment_reminder_rule(organization=org, rule=updated, actor=user)
    assert not PaymentReminderRule.all_tenants.filter(pk=rule.pk).exists()


def test_payment_reminder_due_date_matching_and_delivery(reminder_setup: dict[str, Any]):
    """Ensure reminder rules accurately target invoices based on due dates and send emails."""
    org = reminder_setup["org_a"]
    user = reminder_setup["admin_user"]
    wh = reminder_setup["wh_a"]
    customer = reminder_setup["customer_a"]
    prod = reminder_setup["product"]

    fake_adapter = get_email_adapter()
    fake_adapter.clear()

    today = datetime.date(2026, 6, 15)

    # Create 3 rules:
    # Rule 1: -3 days before due (target due date = 2026-06-18)
    services.create_payment_reminder_rule(
        organization=org,
        name="3 Days Before Due",
        timing_days=-3,
        actor=user,
    )
    # Rule 2: 0 on due date (target due date = 2026-06-15)
    services.create_payment_reminder_rule(
        organization=org,
        name="On Due Date",
        timing_days=0,
        actor=user,
    )
    # Rule 3: +7 days overdue (target due date = 2026-06-08)
    services.create_payment_reminder_rule(
        organization=org,
        name="7 Days Overdue",
        timing_days=7,
        actor=user,
    )

    # Invoice 1: Due in 3 days (matches Rule 1)
    inv1 = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=wh,
        invoice_date=today - datetime.timedelta(days=27),
        due_date=today + datetime.timedelta(days=3),
        lines=[{"product_id": prod.pk, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
        actor=user,
    )
    services.post_invoice(organization=org, invoice=inv1, actor=user)

    # Invoice 2: Due today (matches Rule 2)
    inv2 = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=wh,
        invoice_date=today - datetime.timedelta(days=30),
        due_date=today,
        lines=[{"product_id": prod.pk, "quantity": Decimal("2.0000"), "unit_price": Decimal("100.0000")}],
        actor=user,
    )
    services.post_invoice(organization=org, invoice=inv2, actor=user)

    # Invoice 3: 7 days overdue (matches Rule 3)
    inv3 = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=wh,
        invoice_date=today - datetime.timedelta(days=37),
        due_date=today - datetime.timedelta(days=7),
        lines=[{"product_id": prod.pk, "quantity": Decimal("3.0000"), "unit_price": Decimal("100.0000")}],
        actor=user,
    )
    services.post_invoice(organization=org, invoice=inv3, actor=user)

    # Run dispatch for today
    results = services.process_due_payment_reminders(
        organization=org,
        as_of_date=today,
        actor=user,
    )

    assert len(results["sent"]) == 3
    assert len(fake_adapter.outbox) == 3

    # Check template interpolation in email
    subjects = [email.subject for email in fake_adapter.outbox]
    assert any(inv1.invoice_number in s for s in subjects)
    assert any(inv2.invoice_number in s for s in subjects)
    assert any(inv3.invoice_number in s for s in subjects)

    # Verify audit logs created
    logs = PaymentReminderLog.all_tenants.filter(organization=org)
    assert logs.count() == 3
    assert set(logs.values_list("timing_days", flat=True)) == {-3, 0, 7}


def test_payment_reminder_duplicate_suppression(reminder_setup: dict[str, Any]):
    """Second execution on the same day must not send duplicate emails for already processed stages."""
    org = reminder_setup["org_a"]
    user = reminder_setup["admin_user"]
    wh = reminder_setup["wh_a"]
    customer = reminder_setup["customer_a"]
    prod = reminder_setup["product"]

    fake_adapter = get_email_adapter()
    fake_adapter.clear()

    today = datetime.date(2026, 6, 15)

    services.create_payment_reminder_rule(
        organization=org,
        name="Due Today",
        timing_days=0,
        actor=user,
    )

    inv = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=wh,
        invoice_date=today - datetime.timedelta(days=30),
        due_date=today,
        lines=[{"product_id": prod.pk, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
        actor=user,
    )
    services.post_invoice(organization=org, invoice=inv, actor=user)

    # 1st dispatch -> sends email
    res1 = services.process_due_payment_reminders(organization=org, as_of_date=today, actor=user)
    assert len(res1["sent"]) == 1
    assert len(fake_adapter.outbox) == 1

    # 2nd dispatch on same day -> duplicate suppressed!
    res2 = services.process_due_payment_reminders(organization=org, as_of_date=today, actor=user)
    assert len(res2["sent"]) == 0
    assert len(res2["skipped"]) == 1
    assert "already sent" in res2["skipped"][0]["reason"]
    assert len(fake_adapter.outbox) == 1  # No new emails added


def test_payment_reminder_skips_paid_or_draft_invoices(reminder_setup: dict[str, Any]):
    """Draft or fully paid invoices must not receive reminders."""
    org = reminder_setup["org_a"]
    user = reminder_setup["admin_user"]
    wh = reminder_setup["wh_a"]
    customer = reminder_setup["customer_a"]
    prod = reminder_setup["product"]

    today = datetime.date(2026, 6, 15)

    services.create_payment_reminder_rule(
        organization=org,
        name="Due Today",
        timing_days=0,
        actor=user,
    )

    # Draft invoice due today
    services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=wh,
        invoice_date=today - datetime.timedelta(days=30),
        due_date=today,
        lines=[{"product_id": prod.pk, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
        actor=user,
    )

    results = services.process_due_payment_reminders(organization=org, as_of_date=today, actor=user)
    assert len(results["sent"]) == 0


def test_payment_reminder_skips_when_preference_disabled(reminder_setup: dict[str, Any]):
    """When tenant has disabled payment reminders in NotificationPreference, reminders are skipped."""
    org = reminder_setup["org_a"]
    user = reminder_setup["admin_user"]
    wh = reminder_setup["wh_a"]
    customer = reminder_setup["customer_a"]
    prod = reminder_setup["product"]

    today = datetime.date(2026, 6, 15)

    services.create_payment_reminder_rule(
        organization=org,
        name="Due Today",
        timing_days=0,
        actor=user,
    )

    inv = services.create_invoice(
        organization=org,
        customer=customer,
        warehouse=wh,
        invoice_date=today - datetime.timedelta(days=30),
        due_date=today,
        lines=[{"product_id": prod.pk, "quantity": Decimal("1.0000"), "unit_price": Decimal("100.0000")}],
        actor=user,
    )
    services.post_invoice(organization=org, invoice=inv, actor=user)

    # Disable payment reminder preference
    NotificationPreference.objects.create(
        organization=org,
        category="payment_reminders",
        channel="email",
        is_enabled=False,
    )

    results = services.process_due_payment_reminders(organization=org, as_of_date=today, actor=user)
    assert len(results["sent"]) == 0
    assert len(results["skipped"]) == 1
    assert "disabled" in results["skipped"][0]["reason"]


def test_payment_reminder_api_crud_and_dispatch(reminder_setup: dict[str, Any]):
    """Test REST API endpoints for reminder rules and logs."""
    client = reminder_setup["client"]

    # Create rule via API
    rule_data = {
        "name": "API 5d Overdue",
        "timing_days": 5,
        "is_active": True,
        "subject_template": "Urgent: {{ invoice_number }} Overdue",
        "body_template": "Please pay immediately.",
    }
    create_res = client.post("/api/v1/sales/payment-reminders/rules/", rule_data, format="json")
    assert create_res.status_code == status.HTTP_201_CREATED
    rule_public_id = create_res.data["public_id"]

    # List rules
    list_res = client.get("/api/v1/sales/payment-reminders/rules/")
    assert list_res.status_code == status.HTTP_200_OK
    assert len(list_res.data["results"]) == 1

    # Dispatch now endpoint
    dispatch_res = client.post("/api/v1/sales/payment-reminders/logs/dispatch_now/")
    assert dispatch_res.status_code == status.HTTP_200_OK
    assert "sent_count" in dispatch_res.data

    # Cross-tenant isolation check
    other_client = APIClient()
    other_client.force_authenticate(user=reminder_setup["other_user"])
    iso_res = other_client.get(f"/api/v1/sales/payment-reminders/rules/{rule_public_id}/")
    assert iso_res.status_code == status.HTTP_404_NOT_FOUND
