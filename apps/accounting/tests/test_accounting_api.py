"""Tests for accounting DRF REST API endpoints under /api/v1/accounting/."""

from __future__ import annotations

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting.models import Account, FiscalPeriod
from apps.accounting.services import seed_chart_of_accounts, seed_fiscal_calendar
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def owner(db: None) -> User:
    seed_default_plans()
    return User.objects.create_user(email="api_cfo@example.com", password="Password123!")


@pytest.fixture
def org(owner: User) -> Organization:
    o = provision_organization(name="API Accounting Corp", slug="api-acct-corp", owner=owner, plan="business")
    seed_chart_of_accounts(organization=o)
    seed_fiscal_calendar(organization=o)
    return o


@pytest.fixture
def client(owner: User, org: Organization) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=owner)
    c.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.public_id)
    return c


@pytest.mark.django_db
def test_accounts_api(client: APIClient, org: Organization) -> None:
    # List accounts
    res = client.get("/api/v1/accounting/accounts/")
    assert res.status_code == status.HTTP_200_OK
    assert len(res.data.get("results", res.data)) >= 20

    # Create new account
    payload = {
        "code": "1090",
        "name": "Short-Term Investments",
        "type": "asset",
        "currency": "USD",
        "description": "Certificates of deposit",
    }
    res_create = client.post("/api/v1/accounting/accounts/", payload, format="json")
    assert res_create.status_code == status.HTTP_201_CREATED
    assert res_create.data["code"] == "1090"


@pytest.mark.django_db
def test_journals_api(client: APIClient, org: Organization) -> None:
    cash = Account.all_tenants.get(organization=org, code="1010")
    rev = Account.all_tenants.get(organization=org, code="4000")

    payload = {
        "date": str(timezone.now().date()),
        "memo": "API consulting revenue entry",
        "lines": [
            {"account_id": cash.pk, "debit": "750.00", "credit": "0.00", "memo": "Cash"},
            {"account_id": rev.pk, "debit": "0.00", "credit": "750.00", "memo": "Revenue"},
        ],
    }

    res = client.post("/api/v1/accounting/journals/", payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    entry_id = res.data["public_id"]

    # Reverse entry via API
    res_rev = client.post(
        f"/api/v1/accounting/journals/{entry_id}/reverse/", {"reason": "Voided via API"}, format="json"
    )
    assert res_rev.status_code == status.HTTP_200_OK
    assert res_rev.data["status"] == "reversed"


@pytest.mark.django_db
def test_bank_accounts_api(client: APIClient, org: Organization) -> None:
    cash = Account.all_tenants.get(organization=org, code="1010")

    payload = {
        "name": "API Primary Operating",
        "account_number": "ACCT-9999",
        "bank_name": "JPMorgan",
        "gl_account_id": cash.pk,
        "currency": "USD",
        "opening_balance": "5000.00",
    }
    res = client.post("/api/v1/accounting/bank-accounts/", payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    ba_id = res.data["public_id"]
    assert res.data["current_balance"] == "5000.0000"

    # Add transaction
    tx_payload = {
        "date": str(timezone.now().date()),
        "amount": "1200.00",
        "transaction_type": "deposit",
        "payee": "Direct Deposit",
    }
    res_tx = client.post(f"/api/v1/accounting/bank-accounts/{ba_id}/transactions/", tx_payload, format="json")
    assert res_tx.status_code == status.HTTP_201_CREATED
    tx_id = res_tx.data["id"]

    # Reconcile statement
    rec_payload = {
        "statement_date": str(timezone.now().date()),
        "statement_ending_balance": "6200.00",
        "cleared_transaction_ids": [tx_id],
    }
    res_rec = client.post(f"/api/v1/accounting/bank-accounts/{ba_id}/reconcile/", rec_payload, format="json")
    assert res_rec.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
    assert res_rec.data["status"] == "completed"


@pytest.mark.django_db
def test_expenses_api(client: APIClient, org: Organization) -> None:
    cash = Account.all_tenants.get(organization=org, code="1010")
    exp_gl = Account.all_tenants.get(organization=org, code="6000")

    # Category
    cat_payload = {
        "name": "Software Subscriptions",
        "code": "SAAS",
        "gl_account_id": exp_gl.pk,
    }
    res_cat = client.post("/api/v1/accounting/expense-categories/", cat_payload, format="json")
    assert res_cat.status_code == status.HTTP_201_CREATED
    cat_id = res_cat.data["id"]

    # Expense
    exp_payload = {
        "category_id": cat_id,
        "paid_from_account_id": cash.pk,
        "date": str(timezone.now().date()),
        "amount": "200.00",
        "tax_rate": "0.00",
        "payment_method": "credit_card",
        "vendor_name": "GitHub Inc",
    }
    res_exp = client.post("/api/v1/accounting/expenses/", exp_payload, format="json")
    assert res_exp.status_code == status.HTTP_201_CREATED
    exp_id = res_exp.data["public_id"]

    # Post expense
    res_post = client.post(f"/api/v1/accounting/expenses/{exp_id}/post/")
    assert res_post.status_code == status.HTTP_200_OK
    assert res_post.data["status"] == "posted"

    # Void expense
    res_void = client.post(f"/api/v1/accounting/expenses/{exp_id}/void/")
    assert res_void.status_code == status.HTTP_200_OK
    assert res_void.data["status"] == "void"


@pytest.mark.django_db
def test_exchange_rates_api(client: APIClient, org: Organization) -> None:
    payload = {
        "from_currency": "GBP",
        "to_currency": "USD",
        "rate": "1.275000",
        "effective_date": str(timezone.now().date()),
        "source": "api",
    }
    res = client.post("/api/v1/accounting/exchange-rates/", payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    assert res.data["rate"] == "1.275000"


@pytest.mark.django_db
def test_fiscal_periods_api(client: APIClient, org: Organization) -> None:
    period = FiscalPeriod.all_tenants.filter(organization=org).first()
    assert period is not None

    # Close period
    res_close = client.post(f"/api/v1/accounting/fiscal-periods/{period.public_id}/close/")
    assert res_close.status_code == status.HTTP_200_OK
    assert res_close.data["status"] == "closed"

    # Reopen period
    res_reopen = client.post(f"/api/v1/accounting/fiscal-periods/{period.public_id}/reopen/")
    assert res_reopen.status_code == status.HTTP_200_OK
    assert res_reopen.data["status"] == "open"


@pytest.mark.django_db
def test_tax_summary_api(client: APIClient, org: Organization) -> None:
    today = str(timezone.now().date())
    res = client.post(
        "/api/v1/accounting/tax-summaries/calculate/",
        {"period_start": today, "period_end": today, "save": True},
        format="json",
    )
    assert res.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED)
    sum_id = res.data["public_id"]

    # File return
    res_file = client.post(f"/api/v1/accounting/tax-summaries/{sum_id}/file_return/")
    assert res_file.status_code == status.HTTP_200_OK
    assert res_file.data["status"] == "filed"
