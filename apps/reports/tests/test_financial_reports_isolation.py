"""Tenant Isolation Tests for Financial and Management Accounting Reports.

Ensures that financial reports run for Org A never include data from Org B.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounting.models import (
    Account,
    AccountType,
    JournalEntry,
    JournalLine,
)
from apps.customers.models import Customer
from apps.purchasing.models import Supplier, SupplierBill
from apps.reports.selectors import (
    get_aged_payables_report,
    get_aged_receivables_report,
    get_trial_balance_report,
)
from apps.sales.models import Invoice
from apps.tenancy.models import Warehouse
from apps.tenancy.services import provision_organization


@pytest.fixture
def other_org(db, user):
    org = provision_organization(
        name="Competitor Org",
        slug="competitor-org",
        owner=user,
        base_currency="USD",
    )
    return org


@pytest.mark.django_db
class TestFinancialReportsIsolation:
    def test_trial_balance_tenant_isolation(self, organization, other_org, user):
        """Org A's trial balance must not include accounts or balances from Org B."""
        # Org A account & transaction
        acc_a, _ = Account.all_tenants.update_or_create(
            organization=organization,
            code="1000",
            defaults={"name": "Org A Cash", "type": AccountType.ASSET, "is_active": True},
        )
        entry_a = JournalEntry.objects.create(
            organization=organization,
            entry_number="JE-A-01",
            date=date.today(),
            status=JournalEntry.STATUS_POSTED,
            created_by=user,
            source_type="manual",
            total_debit=Decimal("100.0000"),
            total_credit=Decimal("100.0000"),
        )
        JournalLine.objects.create(
            organization=organization,
            entry=entry_a,
            account=acc_a,
            debit=Decimal("100.0000"),
            credit=Decimal("0.0000"),
        )

        # Org B account & transaction
        acc_b, _ = Account.all_tenants.update_or_create(
            organization=other_org,
            code="1000",
            defaults={"name": "Org B Secret Vault", "type": AccountType.ASSET, "is_active": True},
        )
        entry_b = JournalEntry.objects.create(
            organization=other_org,
            entry_number="JE-B-01",
            date=date.today(),
            status=JournalEntry.STATUS_POSTED,
            created_by=user,
            source_type="manual",
            total_debit=Decimal("999999.0000"),
            total_credit=Decimal("999999.0000"),
        )
        JournalLine.objects.create(
            organization=other_org,
            entry=entry_b,
            account=acc_b,
            debit=Decimal("999999.0000"),
            credit=Decimal("0.0000"),
        )

        report_a = get_trial_balance_report(organization, as_of_date=date.today())

        assert report_a["total_debit"] == Decimal("100.0000")
        account_names = [r["name"] for r in report_a["rows"]]
        assert "Org A Cash" in account_names
        assert "Org B Secret Vault" not in account_names

    def test_aged_receivables_tenant_isolation(self, organization, other_org, user):
        """Org A's aged receivables must not include customers or invoices from Org B."""
        cust_a = Customer.objects.create(organization=organization, name="Customer Alpha")
        wh_a = Warehouse.all_tenants.filter(organization=organization).first()
        Invoice.objects.create(
            organization=organization,
            customer=cust_a,
            created_by=user,
            warehouse=wh_a,
            invoice_number="INV-A-1",
            invoice_date=date.today(),
            status="posted",
            grand_total=Decimal("500.0000"),
            amount_paid=Decimal("0.0000"),
            balance_due=Decimal("500.0000"),
        )

        cust_b = Customer.objects.create(organization=other_org, name="Competitor Secret Client")
        wh_b = Warehouse.all_tenants.filter(organization=other_org).first()
        Invoice.objects.create(
            organization=other_org,
            customer=cust_b,
            created_by=user,
            warehouse=wh_b,
            invoice_number="INV-B-1",
            invoice_date=date.today(),
            status="posted",
            grand_total=Decimal("5000000.0000"),
            amount_paid=Decimal("0.0000"),
            balance_due=Decimal("5000000.0000"),
        )

        report_a = get_aged_receivables_report(organization, as_of_date=date.today())

        assert report_a["summary"]["grand_total"] == Decimal("500.0000")
        client_names = [r["customer_name"] for r in report_a["rows"]]
        assert "Customer Alpha" in client_names
        assert "Competitor Secret Client" not in client_names

    def test_aged_payables_tenant_isolation(self, organization, other_org, user):
        """Org A's aged payables must not include suppliers or bills from Org B."""
        supp_a = Supplier.objects.create(organization=organization, name="Supplier One")
        SupplierBill.objects.create(
            organization=organization,
            supplier=supp_a,
            created_by=user,
            bill_number="BILL-A-1",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status="posted",
            total_amount=Decimal("300.0000"),
            balance_due=Decimal("300.0000"),
        )

        supp_b = Supplier.objects.create(organization=other_org, name="Competitor Vendor")
        SupplierBill.objects.create(
            organization=other_org,
            supplier=supp_b,
            created_by=user,
            bill_number="BILL-B-1",
            issue_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            status="posted",
            total_amount=Decimal("7777777.0000"),
            balance_due=Decimal("7777777.0000"),
        )

        report_a = get_aged_payables_report(organization, as_of_date=date.today())

        assert report_a["summary"]["grand_total"] == Decimal("300.0000")
        vendor_names = [r["supplier_name"] for r in report_a["rows"]]
        assert "Supplier One" in vendor_names
        assert "Competitor Vendor" not in vendor_names
