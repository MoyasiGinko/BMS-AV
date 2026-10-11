"""Tests for Financial Reports Web Views & Export functionality."""

from datetime import date

import pytest
from django.urls import reverse

from apps.accounting.models import Account, AccountType


@pytest.fixture
def auth_client(client, user, organization):
    """Authenticate client with active user and organization session."""
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    return client


@pytest.fixture
def sample_accounts(organization):
    """Create sample accounts for view rendering."""
    acc_cash, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="1000",
        defaults={
            "name": "Operating Cash",
            "type": AccountType.ASSET,
            "is_active": True,
        },
    )
    acc_rev, _ = Account.all_tenants.update_or_create(
        organization=organization,
        code="4000",
        defaults={
            "name": "Consulting Sales",
            "type": AccountType.REVENUE,
            "is_active": True,
        },
    )
    return acc_cash, acc_rev


@pytest.mark.django_db
class TestFinancialReportViews:
    def test_trial_balance_view_get(self, auth_client, sample_accounts):
        url = reverse("reports:trial_balance")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "Trial Balance" in response.content.decode()
        assert "Operating Cash" in response.content.decode()

    def test_profit_and_loss_view_get(self, auth_client, sample_accounts):
        url = reverse("reports:profit_and_loss")
        response = auth_client.get(url)
        content = response.content.decode()
        assert "Profit &amp; Loss" in content or "Profit & Loss" in content

    def test_balance_sheet_view_get(self, auth_client, sample_accounts):
        url = reverse("reports:balance_sheet")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "Balance Sheet" in response.content.decode()

    def test_cash_flow_view_get(self, auth_client, sample_accounts):
        url = reverse("reports:cash_flow")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "Cash Flow Statement" in response.content.decode()

    def test_general_ledger_view_get(self, auth_client, sample_accounts):
        url = reverse("reports:general_ledger")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "General Ledger" in response.content.decode()

    def test_aged_receivables_view_get(self, auth_client):
        url = reverse("reports:aged_receivables")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "Aged Accounts Receivable" in response.content.decode()

    def test_aged_payables_view_get(self, auth_client):
        url = reverse("reports:aged_payables")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "Aged Accounts Payable" in response.content.decode()

    def test_tax_summary_view_get(self, auth_client):
        url = reverse("reports:tax_summary")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert "Tax Summary" in response.content.decode()

    @pytest.mark.parametrize("file_format", ["csv", "xlsx", "pdf"])
    def test_export_trial_balance(self, auth_client, sample_accounts, file_format):
        url = reverse("reports:export")
        data = {
            "report_type": "trial_balance",
            "file_format": file_format,
            "as_of_date": date.today().isoformat(),
        }
        response = auth_client.post(url, data=data)
        assert response.status_code == 200
        assert "attachment; filename=" in response.headers.get("Content-Disposition", "")

    @pytest.mark.parametrize(
        "report_type",
        [
            "profit_and_loss",
            "balance_sheet",
            "cash_flow",
            "general_ledger",
            "aged_receivables",
            "aged_payables",
            "tax_summary",
        ],
    )
    def test_export_all_reports_csv(self, auth_client, sample_accounts, report_type):
        url = reverse("reports:export")
        data = {
            "report_type": report_type,
            "file_format": "csv",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "as_of_date": "2026-12-31",
        }
        response = auth_client.post(url, data=data)
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("Content-Type", "")

    def test_unsupported_export_type(self, auth_client):
        url = reverse("reports:export")
        data = {
            "report_type": "nonexistent_report",
            "file_format": "csv",
        }
        response = auth_client.post(url, data=data)
        assert response.status_code == 400
