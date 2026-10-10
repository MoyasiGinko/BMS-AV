"""Tests for Accounting full-stack Django views and HTMX partials."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import Account, BankAccount, Expense, ExpenseCategory, JournalEntry
from apps.accounting.services import seed_chart_of_accounts, seed_fiscal_calendar
from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def owner(db: None) -> User:
    seed_default_plans()
    return User.objects.create_user(email="view_cfo@example.com", password="Password123!")


@pytest.fixture
def org(owner: User) -> Organization:
    o = provision_organization(
        name="Views Accounting Corp", slug="views-acct-corp", owner=owner, plan="business"
    )
    seed_chart_of_accounts(organization=o)
    seed_fiscal_calendar(organization=o)
    return o


@pytest.fixture
def client(owner: User, org: Organization) -> Client:
    c = Client()
    c.force_login(owner)
    c.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.public_id)
    session = c.session
    session["active_organization_id"] = str(org.pk)
    session.save()
    return c


@pytest.mark.django_db
def test_accounting_dashboard_view(client: Client, org: Organization) -> None:
    res = client.get(reverse("accounting:dashboard"), headers={"host": "localhost"})
    assert res.status_code == 200
    assert b"Accounting &amp; Finance" in res.content or b"Accounting & Finance" in res.content


@pytest.mark.django_db
def test_account_views(client: Client, org: Organization) -> None:
    # List view
    res = client.get(reverse("accounting:account_list"), headers={"host": "localhost"})
    assert res.status_code == 200
    assert b"Chart of Accounts" in res.content

    # HTMX partial
    res_htmx = client.get(
        reverse("accounting:account_list"),
        headers={"host": "localhost", "HX-Request": "true"},
    )
    assert res_htmx.status_code == 200
    assert b"<table" in res_htmx.content

    # Create account
    create_payload = {
        "code": "1080",
        "name": "Marketable Securities",
        "type": "asset",
        "currency": "USD",
        "description": "Short term bonds",
        "is_active": True,
    }
    res_post = client.post(
        reverse("accounting:account_create"), create_payload, headers={"host": "localhost"}
    )
    assert res_post.status_code == 302
    assert Account.all_tenants.filter(organization=org, code="1080").exists()


@pytest.mark.django_db
def test_manual_journal_views(client: Client, org: Organization) -> None:
    cash = Account.all_tenants.get(organization=org, code="1010")
    rev = Account.all_tenants.get(organization=org, code="4000")

    # List view
    res_list = client.get(reverse("accounting:journal_list"), headers={"host": "localhost"})
    assert res_list.status_code == 200

    # Create journal
    post_data = {
        "date": str(timezone.now().date()),
        "memo": "Web form manual journal",
        "account_id[]": [str(cash.pk), str(rev.pk)],
        "debit[]": ["300.00", "0.00"],
        "credit[]": ["0.00", "300.00"],
        "line_memo[]": ["Cash debit", "Sales credit"],
    }
    res_create = client.post(reverse("accounting:journal_create"), post_data, headers={"host": "localhost"})
    assert res_create.status_code == 302
    entry = JournalEntry.all_tenants.filter(organization=org, memo="Web form manual journal").first()
    assert entry is not None
    # Detail view
    res_detail = client.get(
        reverse("accounting:journal_detail", kwargs={"pk": entry.pk}), headers={"host": "localhost"}
    )
    assert res_detail.status_code == 200
    assert entry.entry_number.encode() in res_detail.content

    # Reverse
    res_rev = client.post(
        reverse("accounting:journal_reverse", kwargs={"pk": entry.pk}),
        {"reason": "Testing reversal"},
        headers={"host": "localhost"},
    )
    assert res_rev.status_code == 302
    entry.refresh_from_db()
    assert entry.status == "reversed"


@pytest.mark.django_db
def test_bank_views(client: Client, org: Organization) -> None:
    cash = Account.all_tenants.get(organization=org, code="1010")

    # List view
    res = client.get(reverse("accounting:bank_account_list"), headers={"host": "localhost"})
    assert res.status_code == 200

    # Create bank account
    post_data = {
        "name": "Main Checking Account",
        "bank_name": "Bank of America",
        "account_number": "BOA-1234",
        "gl_account": str(cash.pk),
        "currency": "USD",
        "opening_balance": "1500.00",
    }
    res_create = client.post(
        reverse("accounting:bank_account_create"), post_data, headers={"host": "localhost"}
    )
    assert res_create.status_code == 302

    ba = BankAccount.all_tenants.get(organization=org, account_number="BOA-1234")

    # Detail view
    res_detail = client.get(
        reverse("accounting:bank_account_detail", kwargs={"pk": ba.pk}), headers={"host": "localhost"}
    )
    assert res_detail.status_code == 200
    assert b"Main Checking Account" in res_detail.content

    # Create transaction
    tx_data = {
        "date": str(timezone.now().date()),
        "amount": "250.00",
        "transaction_type": "deposit",
        "payee": "Direct Deposit Customer",
    }
    res_tx = client.post(
        reverse("accounting:bank_transaction_create", kwargs={"pk": ba.pk}),
        tx_data,
        headers={"host": "localhost"},
    )
    assert res_tx.status_code == 302

    # Reconcile view
    res_rec_get = client.get(
        reverse("accounting:bank_reconcile", kwargs={"pk": ba.pk}), headers={"host": "localhost"}
    )
    assert res_rec_get.status_code == 200


@pytest.mark.django_db
def test_expense_views(client: Client, org: Organization) -> None:
    cash = Account.all_tenants.get(organization=org, code="1010")
    exp_gl = Account.all_tenants.get(organization=org, code="6000")

    # Expense category list / create
    res_cat = client.post(
        reverse("accounting:expense_category_list"),
        {"name": "Office Supplies", "code": "OFFICE", "gl_account": str(exp_gl.pk)},
        headers={"host": "localhost"},
    )
    assert res_cat.status_code == 302
    cat = ExpenseCategory.all_tenants.get(organization=org, code="OFFICE")

    # Expense create
    exp_data = {
        "category": str(cat.pk),
        "paid_from_account": str(cash.pk),
        "date": str(timezone.now().date()),
        "amount": "85.00",
        "tax_rate": "0.00",
        "currency": "USD",
        "payment_method": "cash",
        "vendor_name": "Staples",
    }
    res_exp = client.post(reverse("accounting:expense_create"), exp_data, headers={"host": "localhost"})
    assert res_exp.status_code == 302

    exp = Expense.all_tenants.get(organization=org, vendor_name="Staples")

    # Detail
    res_detail = client.get(
        reverse("accounting:expense_detail", kwargs={"pk": exp.pk}), headers={"host": "localhost"}
    )
    assert res_detail.status_code == 200

    # Post
    res_post = client.post(
        reverse("accounting:expense_post", kwargs={"pk": exp.pk}), headers={"host": "localhost"}
    )
    assert res_post.status_code == 302
    exp.refresh_from_db()
    assert exp.status == "posted"

    # Void
    res_void = client.post(
        reverse("accounting:expense_void", kwargs={"pk": exp.pk}), headers={"host": "localhost"}
    )
    assert res_void.status_code == 302
    exp.refresh_from_db()
    assert exp.status == "void"


@pytest.mark.django_db
def test_currency_and_fiscal_periods_and_tax_views(client: Client, org: Organization) -> None:
    # Currencies
    res_curr = client.get(reverse("accounting:currency_list"), headers={"host": "localhost"})
    assert res_curr.status_code == 200

    # Fiscal periods
    res_fp = client.get(reverse("accounting:fiscal_period_list"), headers={"host": "localhost"})
    assert res_fp.status_code == 200

    # Tax summary
    res_tax = client.get(reverse("accounting:tax_summary"), headers={"host": "localhost"})
    assert res_tax.status_code == 200
    assert b"Tax Summary" in res_tax.content
