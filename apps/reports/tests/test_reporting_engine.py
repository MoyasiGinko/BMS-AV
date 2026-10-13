"""Comprehensive unit, integration, and isolation tests for the P5-04 reporting engine.

Covers:
1. Custom Report Builder: Dynamic queries, filtering operators, sorting, and aggregations.
2. Saved Reports: CRUD, parameterized execution, and multi-tenant isolation.
3. Report Schedules: Recurrence calculator, execution, fake email delivery, and periodic dispatch.
4. Summary Tables: Rebuilding DailySalesSummary & DailyExpenseSummary and instant query selectors.
5. Web Views & HTMX partials: Builder, saved reports, schedules, and daily summary dashboards.
6. REST API: /api/v1/reports/saved/, schedules/, builder/, summaries/ with permission checks.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounting.models import Account, AccountType, Expense, ExpenseCategory, ExpenseStatus
from apps.accounts.models import User
from apps.core.notifications import FakeEmailAdapter
from apps.core.permissions import set_feature_override
from apps.customers.models import Customer
from apps.reports import selectors, services
from apps.reports.models import (
    ExportFileFormat,
    ReportSchedule,
    ReportType,
    ScheduleFrequency,
)
from apps.reports.tasks import (
    dispatch_due_report_schedules_task,
    refresh_daily_summaries_task,
    run_report_schedule_task,
)
from apps.sales.models import Invoice, InvoiceStatus, SalesOrder, SalesOrderStatus
from apps.tenancy.models import Branch, Membership, Organization, Role, Warehouse


@pytest.fixture
def reporting_setup(db: None) -> dict[str, Any]:
    """Fixture providing two isolated organizations, users, roles, and operational records."""
    FakeEmailAdapter.clear()

    # Org 1
    org1 = Organization.objects.create(name="Alpha Corp", slug="alpha-corp", base_currency="USD")
    set_feature_override(org1, "reports", True)

    user1 = User.objects.create_user(email="alpha.manager@alphacorp.com", password="Password123!")
    role1 = Role.objects.create(
        organization=org1,
        name="Reporting Admin",
        permissions=["reports.view", "reports.export", "reports.manage", "reports.schedule", "sales.view"],
    )
    Membership.objects.create(organization=org1, user=user1, role=role1, is_owner=True, status="active")

    branch1 = Branch.objects.create(organization=org1, name="Alpha HQ", code="A-HQ")
    warehouse1 = Warehouse.objects.create(
        organization=org1, branch=branch1, name="Alpha Main WH", is_default=True
    )

    cust1 = Customer.objects.create(
        organization=org1,
        name="Alpha Customer 1",
        code="AC-001",
        email="client1@example.com",
        current_balance=Decimal("150.0000"),
    )

    so1 = SalesOrder.objects.create(
        organization=org1,
        order_number="SO-ALPHA-001",
        customer=cust1,
        branch=branch1,
        warehouse=warehouse1,
        order_date=timezone.localdate(),
        status=SalesOrderStatus.CONFIRMED,
        subtotal=Decimal("1000.0000"),
        tax_total=Decimal("100.0000"),
        grand_total=Decimal("1100.0000"),
    )

    inv1 = Invoice.objects.create(
        organization=org1,
        invoice_number="INV-ALPHA-001",
        customer=cust1,
        branch=branch1,
        warehouse=warehouse1,
        invoice_date=timezone.localdate(),
        status=InvoiceStatus.POSTED,
        subtotal=Decimal("1000.0000"),
        tax_total=Decimal("100.0000"),
        grand_total=Decimal("1100.0000"),
        balance_due=Decimal("1100.0000"),
    )

    exp_acc = Account.objects.create(
        organization=org1,
        type=AccountType.EXPENSE,
        code="6001",
        name="Office Supplies",
        currency="USD",
    )
    exp_cat = ExpenseCategory.objects.create(
        organization=org1,
        code="CAT-OFFICE",
        name="Office & Stationery",
        gl_account=exp_acc,
    )
    exp1 = Expense.objects.create(
        organization=org1,
        expense_number="EXP-ALPHA-001",
        category=exp_cat,
        paid_from_account=exp_acc,
        date=timezone.localdate(),
        vendor_name="Stationery Mart",
        amount=Decimal("250.0000"),
        tax_amount=Decimal("25.0000"),
        total_amount=Decimal("275.0000"),
        base_amount=Decimal("275.0000"),
        status=ExpenseStatus.POSTED,
    )

    # Org 2 (Tenant Isolation testing)
    org2 = Organization.objects.create(name="Beta Corp", slug="beta-corp", base_currency="EUR")
    set_feature_override(org2, "reports", True)

    user2 = User.objects.create_user(email="beta.manager@betacorp.com", password="Password123!")
    role2 = Role.objects.create(
        organization=org2,
        name="Beta Admin",
        permissions=["reports.view", "reports.export", "reports.manage", "reports.schedule"],
    )
    Membership.objects.create(organization=org2, user=user2, role=role2, is_owner=True, status="active")

    cust2 = Customer.objects.create(
        organization=org2,
        name="Beta Customer 2",
        code="BC-002",
        email="client2@beta.com",
        current_balance=Decimal("999.0000"),
    )

    # Low privilege user for Org 1 (no manage/schedule)
    user_viewer = User.objects.create_user(email="alpha.viewer@alphacorp.com", password="Password123!")
    role_viewer = Role.objects.create(
        organization=org1,
        name="Viewer Only",
        permissions=["reports.view"],
    )
    Membership.objects.create(organization=org1, user=user_viewer, role=role_viewer, status="active")

    return {
        "org1": org1,
        "user1": user1,
        "role1": role1,
        "branch1": branch1,
        "warehouse1": warehouse1,
        "cust1": cust1,
        "so1": so1,
        "inv1": inv1,
        "exp1": exp1,
        "exp_cat": exp_cat,
        "org2": org2,
        "user2": user2,
        "cust2": cust2,
        "user_viewer": user_viewer,
    }


# ==============================================================================
# 1. Custom Report Builder Tests
# ==============================================================================


class TestCustomReportBuilder:
    """Verify dynamic report execution over supported domain entities."""

    def test_get_custom_report_entities(self, reporting_setup: dict[str, Any]) -> None:
        entities = selectors.get_custom_report_entities()
        assert "sales_orders" in entities
        assert "invoices" in entities
        assert "expenses" in entities
        assert "customers" in entities
        assert "stock_movements" in entities

        so_spec = entities["sales_orders"]
        assert "order_number" in so_spec["fields"]
        assert "grand_total" in so_spec["fields"]
        assert so_spec["fields"]["grand_total"]["aggregatable"] is True

    def test_execute_custom_report_sales_orders(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        spec = {
            "entity": "sales_orders",
            "fields": ["order_number", "order_date", "status", "grand_total"],
            "filters": [
                {"field": "grand_total", "operator": "gte", "value": "500"},
            ],
            "sort_by": "grand_total",
            "sort_direction": "desc",
        }
        res = selectors.execute_custom_report(org, spec)
        assert res["total_rows"] == 1
        assert res["row_dicts"][0]["order_number"] == "SO-ALPHA-001"
        assert res["aggregates"]["grand_total"] == Decimal("1100.0000")

    def test_execute_custom_report_filters_and_operators(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        # Match with icontains
        spec_match = {
            "entity": "invoices",
            "fields": ["invoice_number", "grand_total"],
            "filters": [{"field": "invoice_number", "operator": "icontains", "value": "alpha"}],
        }
        res = selectors.execute_custom_report(org, spec_match)
        assert res["total_rows"] == 1

        # No match with exact
        spec_nomatch = {
            "entity": "invoices",
            "fields": ["invoice_number", "grand_total"],
            "filters": [{"field": "invoice_number", "operator": "exact", "value": "NON_EXISTENT"}],
        }
        res2 = selectors.execute_custom_report(org, spec_nomatch)
        assert res2["total_rows"] == 0

    def test_execute_custom_report_unsupported_entity(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        with pytest.raises(ValueError, match="Unsupported report entity"):
            selectors.execute_custom_report(org, {"entity": "invalid_entity"})


# ==============================================================================
# 2. Saved Reports Tests
# ==============================================================================


class TestSavedReports:
    """Verify saved report configuration CRUD, execution, and tenant isolation."""

    def test_saved_report_crud_and_run(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        user = reporting_setup["user1"]

        # 1. Create
        rep = services.create_saved_report(
            organization=org,
            actor=user,
            name="Alpha High Value Orders",
            description="Orders over 500",
            report_type=ReportType.CUSTOM,
            custom_query={
                "entity": "sales_orders",
                "fields": ["order_number", "grand_total"],
                "filters": [{"field": "grand_total", "operator": "gte", "value": "500"}],
            },
        )
        assert rep.id is not None
        assert rep.public_id is not None

        # 2. Retrieve via selector
        retrieved = selectors.get_saved_report(org, report_id=rep.public_id)
        assert retrieved is not None
        assert retrieved.name == "Alpha High Value Orders"

        # 3. Update
        updated = services.update_saved_report(
            organization=org,
            actor=user,
            saved_report=rep,
            name="Updated High Value Orders",
        )
        assert updated.name == "Updated High Value Orders"

        # 4. Run saved report
        data = services.run_saved_report(organization=org, actor=user, saved_report=updated)
        assert data["total_rows"] == 1
        assert rep.last_run_at is not None

        # 5. Delete
        services.delete_saved_report(organization=org, actor=user, saved_report=updated)
        assert selectors.get_saved_report(org, report_id=rep.public_id) is None

    def test_saved_report_tenant_isolation(self, reporting_setup: dict[str, Any]) -> None:
        org1 = reporting_setup["org1"]
        user1 = reporting_setup["user1"]
        org2 = reporting_setup["org2"]

        rep = services.create_saved_report(
            organization=org1,
            actor=user1,
            name="Confidential Org1 Report",
            report_type=ReportType.SALES_BY_CUSTOMER,
        )

        # Org2 cannot see Org1's saved report
        org2_list = selectors.list_saved_reports(org2)
        assert not any(r.public_id == rep.public_id for r in org2_list)

        assert selectors.get_saved_report(org2, report_id=rep.public_id) is None


# ==============================================================================
# 3. Automated Report Schedules Tests
# ==============================================================================


class TestReportSchedules:
    """Verify schedule frequency calculation, execution, email delivery, and dispatcher."""

    def test_calculate_next_run_at(self) -> None:
        now = timezone.now()
        time_8am = datetime.time(8, 0)

        # Daily
        daily_next = services.calculate_next_run_at(
            frequency=ScheduleFrequency.DAILY,
            time_of_day=time_8am,
            from_dt=now,
        )
        assert daily_next > now
        assert daily_next.time() == time_8am

        # Weekly
        weekly_next = services.calculate_next_run_at(
            frequency=ScheduleFrequency.WEEKLY,
            time_of_day=time_8am,
            day_of_week=0,  # Monday
            from_dt=now,
        )
        assert weekly_next > now
        assert weekly_next.weekday() == 0

        # Monthly
        monthly_next = services.calculate_next_run_at(
            frequency=ScheduleFrequency.MONTHLY,
            time_of_day=time_8am,
            day_of_month=15,
            from_dt=now,
        )
        assert monthly_next > now
        assert monthly_next.day == 15

    def test_create_and_run_schedule_now(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        user = reporting_setup["user1"]
        FakeEmailAdapter.clear()

        sched = services.create_report_schedule(
            organization=org,
            actor=user,
            name="Weekly Sales Summary",
            report_type=ReportType.SALES_BY_PRODUCT,
            frequency=ScheduleFrequency.WEEKLY,
            format=ExportFileFormat.CSV,
            recipients=["cfo@alphacorp.com", "finance@alphacorp.com"],
        )
        assert sched.id is not None
        assert sched.next_run_at is not None

        filename, file_bytes, _row_count = services.run_report_schedule_now(
            organization=org,
            schedule=sched,
            actor=user,
        )

        assert filename.endswith(".csv")
        assert len(file_bytes) > 0
        sched.refresh_from_db()
        assert sched.last_run_at is not None

        # Verify email was dispatched into FakeEmailAdapter
        assert len(FakeEmailAdapter.outbox) == 1
        sent_email = FakeEmailAdapter.outbox[0]
        assert "Weekly Sales Summary" in sent_email.subject
        assert "cfo@alphacorp.com" in sent_email.recipient_list
        assert "finance@alphacorp.com" in sent_email.recipient_list

    def test_dispatch_due_report_schedules(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        user = reporting_setup["user1"]
        FakeEmailAdapter.clear()

        sched = services.create_report_schedule(
            organization=org,
            actor=user,
            name="Due Daily Schedule",
            report_type=ReportType.SALES_BY_CUSTOMER,
            frequency=ScheduleFrequency.DAILY,
            format=ExportFileFormat.PDF,
            recipients=["exec@alphacorp.com"],
        )

        # Force schedule to be past due
        past = timezone.now() - datetime.timedelta(hours=2)
        sched.next_run_at = past
        sched.save(update_fields=["next_run_at"])

        count = services.dispatch_due_report_schedules()
        assert count >= 1

        sched.refresh_from_db()
        assert sched.next_run_at > timezone.now()
        assert len(FakeEmailAdapter.outbox) >= 1

    def test_celery_periodic_tasks(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        user = reporting_setup["user1"]

        sched = services.create_report_schedule(
            organization=org,
            actor=user,
            name="Celery Task Schedule",
            report_type=ReportType.SALES_BY_CUSTOMER,
            recipients=["ops@alphacorp.com"],
        )

        # Run single schedule task
        res_single = run_report_schedule_task(str(sched.public_id))
        assert "completed" in res_single.lower() or "sales_by_customer" in res_single.lower()

        # Run periodic dispatcher task
        res_disp = dispatch_due_report_schedules_task()
        assert "Dispatched" in res_disp

        # Run summaries refresher task
        res_sum = refresh_daily_summaries_task(days_back=1)
        assert "Refreshed daily summaries" in res_sum


# ==============================================================================
# 4. Daily Summary Tables Tests
# ==============================================================================


class TestDailySummaries:
    """Verify aggregation into pre-computed summary tables and selector queries."""

    def test_rebuild_and_query_daily_sales_summary(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        today = timezone.localdate()

        count = services.rebuild_daily_sales_summary(
            organization=org,
            start_date=today,
            end_date=today,
        )
        assert count > 0

        # Query using selector
        data = selectors.get_daily_sales_summary_data(
            organization=org,
            start_date=today,
            end_date=today,
        )
        assert len(data["records"]) > 0
        summary = data["summary"]
        assert summary["total_invoices"] >= 1
        assert summary["net_sales"] == Decimal("1100.0000")

    def test_rebuild_and_query_daily_expense_summary(self, reporting_setup: dict[str, Any]) -> None:
        org = reporting_setup["org1"]
        today = timezone.localdate()

        count = services.rebuild_daily_expense_summary(
            organization=org,
            start_date=today,
            end_date=today,
        )
        assert count > 0

        # Query using selector
        data = selectors.get_daily_expense_summary_data(
            organization=org,
            start_date=today,
            end_date=today,
        )
        assert len(data["records"]) >= 1
        summary = data["summary"]
        assert summary["total_count"] >= 1
        assert summary["total_amount"] == Decimal("250.0000")

    def test_daily_summary_tenant_isolation(self, reporting_setup: dict[str, Any]) -> None:
        org1 = reporting_setup["org1"]
        org2 = reporting_setup["org2"]
        today = timezone.localdate()

        services.rebuild_daily_sales_summary(organization=org1, start_date=today, end_date=today)

        # Org2 querying should return zero records
        data_org2 = selectors.get_daily_sales_summary_data(
            organization=org2,
            start_date=today,
            end_date=today,
        )
        assert len(data_org2["records"]) == 0
        assert data_org2["summary"]["total_invoices"] == 0


# ==============================================================================
# 5. Web Views & HTMX Partial Tests
# ==============================================================================


class TestReportingWebViews:
    """Verify HTML views and HTMX partial responses."""

    def test_saved_reports_web_views(self, reporting_setup: dict[str, Any]) -> None:
        client = Client()
        client.force_login(reporting_setup["user1"])
        org = reporting_setup["org1"]

        # Create saved report
        rep = services.create_saved_report(
            organization=org,
            actor=reporting_setup["user1"],
            name="Web Test Saved Report",
            report_type=ReportType.SALES_BY_PRODUCT,
        )

        # List view
        url_list = reverse("reports:saved_reports")
        resp = client.get(url_list)
        assert resp.status_code == 200
        assert "Web Test Saved Report" in resp.content.decode()

        # Detail view
        url_detail = reverse("reports:saved_report_detail", kwargs={"report_id": str(rep.public_id)})
        resp_det = client.get(url_detail)
        assert resp_det.status_code == 200
        assert "Web Test Saved Report" in resp_det.content.decode()

        # Delete view
        url_del = reverse("reports:saved_report_delete", kwargs={"report_id": str(rep.public_id)})
        resp_del = client.post(url_del)
        assert resp_del.status_code == 302
        assert selectors.get_saved_report(org, report_id=rep.public_id) is None

    def test_report_builder_web_views(self, reporting_setup: dict[str, Any]) -> None:
        client = Client()
        client.force_login(reporting_setup["user1"])

        # Builder index
        url_bld = reverse("reports:builder")
        resp = client.get(url_bld)
        assert resp.status_code == 200
        assert "Report Builder" in resp.content.decode()

        # HTMX Preview partial
        url_prev = reverse("reports:builder_preview")
        resp_prev = client.get(
            url_prev,
            {"entity": "sales_orders", "fields": ["order_number", "grand_total"]},
        )
        assert resp_prev.status_code == 200
        assert "SO-ALPHA-001" in resp_prev.content.decode()

        # Save builder report
        url_save = reverse("reports:builder_save")
        resp_save = client.post(
            url_save,
            {
                "name": "Builder Saved Test",
                "entity": "sales_orders",
                "fields": ["order_number", "grand_total"],
            },
        )
        assert resp_save.status_code == 302

    def test_report_schedules_web_views(self, reporting_setup: dict[str, Any]) -> None:
        client = Client()
        client.force_login(reporting_setup["user1"])
        org = reporting_setup["org1"]

        # Schedules list
        url_list = reverse("reports:schedules")
        resp = client.get(url_list)
        assert resp.status_code == 200

        # Create saved report first for schedule linkage
        saved_rep = services.create_saved_report(
            organization=org,
            actor=reporting_setup["user1"],
            name="Schedule Target Report",
            report_type=ReportType.SALES_BY_PRODUCT,
        )

        # Schedule create
        url_create = reverse("reports:schedule_create")
        resp_create = client.post(
            url_create,
            {
                "name": "Web Created Schedule",
                "saved_report": str(saved_rep.pk),
                "frequency": ScheduleFrequency.WEEKLY,
                "format": ExportFileFormat.PDF,
                "recipient_emails": "exec@alpha.com, cfo@alpha.com",
                "is_active": "on",
            },
        )
        assert resp_create.status_code == 302

        created = ReportSchedule.all_tenants.filter(organization=org, name="Web Created Schedule").first()
        assert created is not None
        assert "exec@alpha.com" in created.recipients

        # Run Now action
        url_run = reverse("reports:schedule_run_now", kwargs={"schedule_id": str(created.public_id)})
        resp_run = client.post(url_run)
        assert resp_run.status_code == 302

    def test_daily_summaries_web_views(self, reporting_setup: dict[str, Any]) -> None:
        client = Client()
        client.force_login(reporting_setup["user1"])

        url_sum = reverse("reports:daily_summaries")
        resp = client.get(url_sum)
        assert resp.status_code == 200
        assert "Executive Daily Summaries" in resp.content.decode()

        # Rebuild view
        url_reb = reverse("reports:daily_summaries_rebuild")
        resp_reb = client.post(url_reb)
        assert resp_reb.status_code == 302


# ==============================================================================
# 6. REST API Tests
# ==============================================================================


class TestReportingAPI:
    """Verify REST API under /api/v1/reports/ with permission enforcement."""

    def test_saved_report_api_crud_and_run(self, reporting_setup: dict[str, Any]) -> None:
        client = APIClient()
        client.force_authenticate(reporting_setup["user1"])
        org = reporting_setup["org1"]

        # Create
        url_create = "/api/v1/reports/saved/"
        payload = {
            "name": "API Saved Report",
            "description": "Created via REST API",
            "report_type": "sales_by_customer",
            "filters": {"search": "Alpha"},
        }
        res_create = client.post(
            url_create, payload, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id)
        )
        assert res_create.status_code == status.HTTP_201_CREATED
        pub_id = res_create.data["public_id"]

        # List
        res_list = client.get(url_create, HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_list.status_code == status.HTTP_200_OK
        assert any(r["public_id"] == pub_id for r in res_list.data["results"])

        # Run action
        url_run = f"/api/v1/reports/saved/{pub_id}/run/"
        res_run = client.post(url_run, {}, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_run.status_code == status.HTTP_200_OK
        assert res_run.data["report_name"] == "API Saved Report"

    def test_report_schedule_api_crud_and_run_now(self, reporting_setup: dict[str, Any]) -> None:
        client = APIClient()
        client.force_authenticate(reporting_setup["user1"])
        org = reporting_setup["org1"]
        FakeEmailAdapter.clear()

        # Create schedule
        url_create = "/api/v1/reports/schedules/"
        payload = {
            "name": "API Delivery Schedule",
            "report_type": "sales_by_product",
            "frequency": "weekly",
            "day_of_week": 1,
            "format": "csv",
            "recipients": ["api.subscriber@alphacorp.com"],
        }
        res_create = client.post(
            url_create, payload, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id)
        )
        assert res_create.status_code == status.HTTP_201_CREATED
        pub_id = res_create.data["public_id"]

        # Run now action
        url_run = f"/api/v1/reports/schedules/{pub_id}/run-now/"
        res_run = client.post(url_run, {}, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_run.status_code == status.HTTP_200_OK
        assert res_run.data["status"] == "success"
        assert len(FakeEmailAdapter.outbox) == 1

    def test_custom_report_builder_api(self, reporting_setup: dict[str, Any]) -> None:
        client = APIClient()
        client.force_authenticate(reporting_setup["user1"])
        org = reporting_setup["org1"]

        # GET entities
        url_bld = "/api/v1/reports/builder/"
        res_meta = client.get(url_bld, HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_meta.status_code == status.HTTP_200_OK
        assert "sales_orders" in res_meta.data["entities"]

        # POST execute query
        query_payload = {
            "entity": "sales_orders",
            "fields": ["order_number", "grand_total"],
            "filters": [{"field": "grand_total", "operator": "gte", "value": "100"}],
        }
        res_exec = client.post(
            url_bld, query_payload, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id)
        )
        assert res_exec.status_code == status.HTTP_200_OK
        assert res_exec.data["total_rows"] == 1
        assert res_exec.data["row_dicts"][0]["order_number"] == "SO-ALPHA-001"

    def test_daily_summaries_api(self, reporting_setup: dict[str, Any]) -> None:
        client = APIClient()
        client.force_authenticate(reporting_setup["user1"])
        org = reporting_setup["org1"]
        today = str(timezone.localdate())

        # POST rebuild
        url_sum = "/api/v1/reports/summaries/"
        rebuild_payload = {"start_date": today, "end_date": today}
        res_reb = client.post(
            url_sum, rebuild_payload, format="json", HTTP_X_ORGANIZATION_ID=str(org.public_id)
        )
        assert res_reb.status_code == status.HTTP_200_OK
        assert res_reb.data["sales_summaries_updated"] > 0

        # GET summary data
        res_get = client.get(
            f"{url_sum}?start_date={today}&end_date={today}",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_get.status_code == status.HTTP_200_OK
        assert "sales" in res_get.data
        assert "expenses" in res_get.data

    def test_api_permission_enforcement(self, reporting_setup: dict[str, Any]) -> None:
        client = APIClient()
        org = reporting_setup["org1"]

        # 1. Unauthenticated request -> 401
        res_unauth = client.get("/api/v1/reports/saved/", HTTP_X_ORGANIZATION_ID=str(org.public_id))
        assert res_unauth.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]

        # 2. Viewer user (has reports.view, but NOT reports.manage) trying to create saved report -> 403
        client.force_authenticate(reporting_setup["user_viewer"])
        payload = {
            "name": "Unauthorized Report",
            "report_type": "sales_by_customer",
        }
        res_perm = client.post(
            "/api/v1/reports/saved/",
            payload,
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert res_perm.status_code == status.HTTP_403_FORBIDDEN
