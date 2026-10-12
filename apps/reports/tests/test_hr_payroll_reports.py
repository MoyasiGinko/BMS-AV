"""Comprehensive tests for HR & Payroll reports and dashboard widgets (P4-05).

Covers:
- Selectors: Headcount, Attendance, Payroll Cost, and Employee Performance
- Dashboard Widgets: Registry, HTML rendering, and HTMX partial refresh
- Report Views: HTTP 200, filters, and access controls
- Permissions: hr.view and payroll.view enforcement
- Cross-tenant isolation
- Background export jobs (CSV, XLSX, PDF)
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.billing.services import create_subscription, seed_default_plans
from apps.core.dashboard import registry
from apps.hr.models import (
    AttendanceRecord,
    AttendanceStatus,
    Employee,
    EmployeeStatus,
    EmploymentType,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveType,
    Position,
    Shift,
)
from apps.payroll.models import (
    PayrollRun,
    PayrollRunStatus,
    Payslip,
    PayslipStatus,
)
from apps.reports import selectors, services
from apps.reports.dashboard_widgets import (
    AttendanceWidget,
    EmployeePerformanceWidget,
    HeadcountWidget,
    PayrollCostWidget,
)
from apps.reports.models import ExportFileFormat, ExportJobStatus, ReportType
from apps.tenancy.models import Branch, Department, Membership, Role
from apps.tenancy.services import create_organization

User = get_user_model()


@pytest.fixture
def hr_payroll_setup(db: None) -> dict[str, object]:
    plans = seed_default_plans()
    owner = User.objects.create_user(email="hr_owner@corp.com", password="password123")
    org = create_organization(name="HR Corp", slug="hr-corp", owner=owner)
    create_subscription(organization=org, plan=plans["enterprise"], actor=owner, trial_days=0)

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    branch = Branch.objects.create(organization=org, name="Main Office", code="HQ")
    dept_eng = Department.objects.create(organization=org, name="Engineering", code="ENG")
    dept_sales = Department.objects.create(organization=org, name="Sales", code="SALES")

    pos_dev = Position.objects.create(organization=org, title="Developer", code="DEV", department=dept_eng)
    pos_rep = Position.objects.create(organization=org, title="Sales Rep", code="REP", department=dept_sales)

    shift = Shift.objects.create(
        organization=org,
        name="Day Shift",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )

    today = timezone.localdate()

    emp1 = Employee.objects.create(
        organization=org,
        code="EMP-001",
        first_name="Alice",
        last_name="Smith",
        work_email="alice@corp.com",
        branch=branch,
        department=dept_eng,
        position=pos_dev,
        default_shift=shift,
        hire_date=today - datetime.timedelta(days=120),
        status=EmployeeStatus.ACTIVE,
        employment_type=EmploymentType.FULL_TIME,
    )

    emp2 = Employee.objects.create(
        organization=org,
        code="EMP-002",
        first_name="Bob",
        last_name="Jones",
        work_email="bob@corp.com",
        branch=branch,
        department=dept_sales,
        position=pos_rep,
        default_shift=shift,
        hire_date=today - datetime.timedelta(days=10),
        status=EmployeeStatus.ACTIVE,
        employment_type=EmploymentType.FULL_TIME,
    )

    emp3 = Employee.objects.create(
        organization=org,
        code="EMP-003",
        first_name="Charlie",
        last_name="Brown",
        work_email="charlie@corp.com",
        branch=branch,
        department=dept_eng,
        position=pos_dev,
        default_shift=shift,
        hire_date=today - datetime.timedelta(days=400),
        termination_date=today - datetime.timedelta(days=30),
        status=EmployeeStatus.TERMINATED,
        employment_type=EmploymentType.FULL_TIME,
    )

    # Attendance records
    check_in_time = timezone.make_aware(datetime.datetime.combine(today, datetime.time(9, 5)))
    AttendanceRecord.objects.create(
        organization=org,
        employee=emp1,
        shift=shift,
        date=today,
        check_in=check_in_time,
        status=AttendanceStatus.PRESENT,
        work_hours=Decimal("8.00"),
    )

    late_check_in = timezone.make_aware(datetime.datetime.combine(today, datetime.time(9, 45)))
    AttendanceRecord.objects.create(
        organization=org,
        employee=emp2,
        shift=shift,
        date=today,
        check_in=late_check_in,
        status=AttendanceStatus.LATE,
        work_hours=Decimal("7.25"),
    )

    # Leave request
    leave_type = LeaveType.objects.create(organization=org, name="Annual Leave", code="ANNUAL")
    LeaveRequest.objects.create(
        organization=org,
        employee=emp1,
        leave_type=leave_type,
        start_date=today - datetime.timedelta(days=5),
        end_date=today - datetime.timedelta(days=4),
        days_count=Decimal("2.00"),
        reason="Vacation",
        status=LeaveRequestStatus.APPROVED,
    )

    # Payroll run
    run = PayrollRun.objects.create(
        organization=org,
        number="PR-TEST-001",
        period_start=today.replace(day=1),
        period_end=today,
        payment_date=today,
        status=PayrollRunStatus.APPROVED,
        total_gross_pay=Decimal("10000.00"),
        total_deductions=Decimal("1500.00"),
        total_net_pay=Decimal("8500.00"),
    )
    Payslip.objects.create(
        organization=org,
        payroll_run=run,
        employee=emp1,
        status=PayslipStatus.DRAFT,
        base_salary=Decimal("6000.00"),
        gross_pay=Decimal("6000.00"),
        total_deductions=Decimal("900.00"),
        net_pay=Decimal("5100.00"),
        working_days=20,
    )
    Payslip.objects.create(
        organization=org,
        payroll_run=run,
        employee=emp2,
        status=PayslipStatus.DRAFT,
        base_salary=Decimal("4000.00"),
        gross_pay=Decimal("4000.00"),
        total_deductions=Decimal("600.00"),
        net_pay=Decimal("3400.00"),
        working_days=20,
    )

    # Staff user with hr.view
    hr_user = User.objects.create_user(email="hr_staff@corp.com", password="password123")
    role_hr = Role.objects.create(
        organization=org,
        name="HR Specialist",
        permissions=["hr.view", "reports.view", "reports.export"],
    )
    Membership.objects.create(organization=org, user=hr_user, role=role_hr, status=Membership.STATUS_ACTIVE)

    # Staff user with payroll.view
    payroll_user = User.objects.create_user(email="payroll_staff@corp.com", password="password123")
    role_payroll = Role.objects.create(
        organization=org,
        name="Payroll Accountant",
        permissions=["payroll.view", "reports.view", "reports.export"],
    )
    Membership.objects.create(
        organization=org, user=payroll_user, role=role_payroll, status=Membership.STATUS_ACTIVE
    )

    # Regular unprivileged user
    unprivileged_user = User.objects.create_user(email="guest@corp.com", password="password123")
    role_guest = Role.objects.create(organization=org, name="Guest", permissions=[])
    Membership.objects.create(
        organization=org, user=unprivileged_user, role=role_guest, status=Membership.STATUS_ACTIVE
    )

    return {
        "org": org,
        "owner": owner,
        "hr_user": hr_user,
        "payroll_user": payroll_user,
        "unprivileged_user": unprivileged_user,
        "emp1": emp1,
        "emp2": emp2,
        "emp3": emp3,
        "run": run,
        "dept_eng": dept_eng,
    }


# ===========================================================================
# 1. Selector Tests
# ===========================================================================


@pytest.mark.django_db(transaction=True)
def test_headcount_kpi_and_report_selectors(hr_payroll_setup: dict[str, object]) -> None:
    org = hr_payroll_setup["org"]

    kpi = selectors.get_headcount_kpi(org)
    assert kpi["total_count"] == 3
    assert kpi["active_count"] == 2
    assert kpi["terminated_count"] == 1
    assert kpi["new_hires_month"] >= 1
    assert len(kpi["departments"]) >= 2

    report = selectors.get_headcount_report(org)
    assert report["summary"]["total_headcount"] == 2  # active and not terminated before as_of
    assert report["summary"]["active_count"] == 2
    assert len(report["rows"]) == 2

    # Filter by department
    dept_eng = hr_payroll_setup["dept_eng"]
    dept_report = selectors.get_headcount_report(org, department_id=dept_eng.id)
    assert len(dept_report["rows"]) == 1
    assert dept_report["rows"][0]["code"] == "EMP-001"


@pytest.mark.django_db(transaction=True)
def test_workforce_attendance_kpi_and_report_selectors(hr_payroll_setup: dict[str, object]) -> None:
    org = hr_payroll_setup["org"]
    today = timezone.localdate()

    kpi = selectors.get_workforce_attendance_kpi(org, today=today)
    assert kpi["scheduled_count"] == 2
    assert kpi["present_count"] == 2
    assert kpi["late_count"] == 1
    assert kpi["attendance_rate"] == 100.0
    assert len(kpi["recent_records"]) == 2

    # Attendance report for past 7 days
    start_d = today - datetime.timedelta(days=7)
    report = selectors.get_workforce_attendance_report(org, start_date=start_d, end_date=today)
    assert report["summary"]["total_employees"] == 2
    assert report["summary"]["total_present_days"] == 2
    assert report["summary"]["total_late_days"] == 1
    assert len(report["rows"]) == 2


@pytest.mark.django_db(transaction=True)
def test_payroll_cost_kpi_and_report_selectors(hr_payroll_setup: dict[str, object]) -> None:
    org = hr_payroll_setup["org"]
    today = timezone.localdate()

    kpi = selectors.get_payroll_cost_kpi(org)
    assert kpi["latest_run"] is not None
    assert kpi["latest_run"]["number"] == "PR-TEST-001"
    assert kpi["gross_pay"] == Decimal("10000.00")
    assert kpi["deductions"] == Decimal("1500.00")
    assert kpi["net_pay"] == Decimal("8500.00")
    assert kpi["avg_compensation"] == Decimal("5000.00")

    # Payroll report
    start_d = today.replace(day=1)
    report = selectors.get_payroll_cost_report(org, start_date=start_d, end_date=today)
    assert report["summary"]["run_count"] == 1
    assert report["summary"]["total_payslips"] == 2
    assert report["summary"]["total_gross_pay"] == Decimal("10000.00")
    assert len(report["departments"]) >= 2


@pytest.mark.django_db(transaction=True)
def test_employee_performance_kpi_and_report_selectors(hr_payroll_setup: dict[str, object]) -> None:
    org = hr_payroll_setup["org"]
    today = timezone.localdate()

    kpi = selectors.get_employee_performance_kpi(org)
    assert kpi["overall_punctuality_rate"] > 0
    assert len(kpi["top_punctual_employees"]) >= 1
    assert "tenure" in kpi

    # Report
    start_d = today - datetime.timedelta(days=30)
    report = selectors.get_employee_performance_report(org, start_date=start_d, end_date=today)
    assert report["summary"]["total_evaluated"] == 2
    assert len(report["rows"]) == 2


# ===========================================================================
# 2. Dashboard Widgets Tests
# ===========================================================================


def test_widget_registry_contains_hr_and_payroll_widgets() -> None:
    """Ensure all 4 widgets are present in the global dashboard registry."""
    assert isinstance(registry.get("headcount"), HeadcountWidget)
    assert isinstance(registry.get("attendance"), AttendanceWidget)
    assert isinstance(registry.get("payroll_cost"), PayrollCostWidget)
    assert isinstance(registry.get("employee_performance"), EmployeePerformanceWidget)


@pytest.mark.django_db(transaction=True)
def test_hr_and_payroll_widgets_render_html(hr_payroll_setup: dict[str, object]) -> None:
    org = hr_payroll_setup["org"]
    owner = hr_payroll_setup["owner"]
    rf = RequestFactory()
    request = rf.get("/dashboard/")
    request.user = owner  # type: ignore
    request.organization = org  # type: ignore

    # Headcount Widget
    hc_widget = registry.get("headcount")
    assert hc_widget is not None
    hc_html = hc_widget.render(request, org)
    assert "Workforce Headcount" in hc_html
    assert "active" in hc_html.lower() or "registered" in hc_html.lower()

    # Attendance Widget
    att_widget = registry.get("attendance")
    assert att_widget is not None
    att_html = att_widget.render(request, org)
    assert "Today's Attendance" in att_html
    assert "present" in att_html.lower()

    # Payroll Cost Widget
    pr_widget = registry.get("payroll_cost")
    assert pr_widget is not None
    pr_html = pr_widget.render(request, org)
    assert "Payroll Cost" in pr_html
    assert "10000" in pr_html or "10,000" in pr_html

    # Employee Performance Widget
    perf_widget = registry.get("employee_performance")
    assert perf_widget is not None
    perf_html = perf_widget.render(request, org)
    assert "Employee Performance" in perf_html


@pytest.mark.django_db(transaction=True)
def test_widget_partial_endpoints(client: Client, hr_payroll_setup: dict[str, object]) -> None:
    owner = hr_payroll_setup["owner"]
    client.force_login(owner)

    for wid in ["headcount", "attendance", "payroll_cost", "employee_performance"]:
        resp = client.get(f"/dashboard/widget/{wid}/", HTTP_HOST="hr-corp.localhost")
        assert resp.status_code == 200, f"Widget partial for {wid} failed with {resp.status_code}"
        assert f"widget-{wid}" in resp.content.decode()


# ===========================================================================
# 3. Report Views & Permissions Tests
# ===========================================================================


@pytest.mark.django_db(transaction=True)
def test_hr_reports_views_success(client: Client, hr_payroll_setup: dict[str, object]) -> None:
    hr_user = hr_payroll_setup["hr_user"]
    client.force_login(hr_user)

    # 1. Headcount
    resp = client.get("/reports/headcount/", HTTP_HOST="hr-corp.localhost")
    assert resp.status_code == 200
    assert "Workforce Headcount & Turnover" in resp.content.decode()

    # 2. Attendance
    resp = client.get("/reports/attendance/", HTTP_HOST="hr-corp.localhost")
    assert resp.status_code == 200
    assert "Workforce Attendance & Leave Analysis" in resp.content.decode()

    # 3. Performance
    resp = client.get("/reports/employee-performance/", HTTP_HOST="hr-corp.localhost")
    assert resp.status_code == 200
    assert "Employee Performance & Reliability Basics" in resp.content.decode()


@pytest.mark.django_db(transaction=True)
def test_payroll_report_view_success(client: Client, hr_payroll_setup: dict[str, object]) -> None:
    payroll_user = hr_payroll_setup["payroll_user"]
    client.force_login(payroll_user)

    resp = client.get("/reports/payroll-cost/", HTTP_HOST="hr-corp.localhost")
    assert resp.status_code == 200
    assert "Payroll Cost & Compensation Analysis" in resp.content.decode()
    assert "PR-TEST-001" in resp.content.decode()


@pytest.mark.django_db(transaction=True)
def test_report_views_permissions_enforced(client: Client, hr_payroll_setup: dict[str, object]) -> None:
    unprivileged_user = hr_payroll_setup["unprivileged_user"]
    client.force_login(unprivileged_user)

    # HR reports denied
    resp1 = client.get("/reports/headcount/", HTTP_HOST="hr-corp.localhost")
    assert resp1.status_code == 403

    resp2 = client.get("/reports/attendance/", HTTP_HOST="hr-corp.localhost")
    assert resp2.status_code == 403

    resp3 = client.get("/reports/employee-performance/", HTTP_HOST="hr-corp.localhost")
    assert resp3.status_code == 403

    # Payroll report denied
    resp4 = client.get("/reports/payroll-cost/", HTTP_HOST="hr-corp.localhost")
    assert resp4.status_code == 403


# ===========================================================================
# 4. Cross-Tenant Isolation Tests
# ===========================================================================


@pytest.mark.django_db(transaction=True)
def test_cross_tenant_isolation_in_hr_payroll_reports(
    hr_payroll_setup: dict[str, object],
) -> None:
    # Ensure Org A setup exists
    assert hr_payroll_setup["org"] is not None

    # Create Org B
    plans = seed_default_plans()
    owner_b = User.objects.create_user(email="owner_b@other.com", password="password123")
    org_b = create_organization(name="Other Corp", slug="other-corp", owner=owner_b)
    create_subscription(organization=org_b, plan=plans["enterprise"], actor=owner_b, trial_days=0)

    # Org B Headcount KPI should be 0
    kpi_b = selectors.get_headcount_kpi(org_b)
    assert kpi_b["total_count"] == 0
    assert kpi_b["active_count"] == 0

    # Org B Attendance KPI should be 0
    att_b = selectors.get_workforce_attendance_kpi(org_b)
    assert att_b["scheduled_count"] == 0
    assert att_b["present_count"] == 0

    # Org B Payroll Cost KPI should be 0
    pr_b = selectors.get_payroll_cost_kpi(org_b)
    assert pr_b["gross_pay"] == Decimal("0.0000")
    assert pr_b["latest_run"] is None

    # Org B Performance KPI should have 0 records
    perf_b = selectors.get_employee_performance_kpi(org_b)
    assert len(perf_b["top_punctual_employees"]) == 0


# ===========================================================================
# 5. Export Jobs Tests
# ===========================================================================


@pytest.mark.django_db(transaction=True)
def test_hr_and_payroll_exports(hr_payroll_setup: dict[str, object]) -> None:
    org = hr_payroll_setup["org"]
    owner = hr_payroll_setup["owner"]

    today = timezone.localdate()
    params = {
        "start_date": str(today - datetime.timedelta(days=30)),
        "end_date": str(today),
    }

    report_types = [
        ReportType.HEADCOUNT,
        ReportType.ATTENDANCE,
        ReportType.PAYROLL_COST,
        ReportType.EMPLOYEE_PERFORMANCE,
    ]

    for r_type in report_types:
        for fmt in [ExportFileFormat.CSV, ExportFileFormat.XLSX, ExportFileFormat.PDF]:
            job = services.create_export_job(
                organization=org,
                report_type=r_type,
                file_format=fmt,
                parameters=params,
                actor=owner,
            )
            assert job.status == ExportJobStatus.PENDING

            processed_job = services.process_export_job(job.public_id)
            assert processed_job.status == ExportJobStatus.COMPLETED
            assert processed_job.file_size > 0
            assert processed_job.file_name.endswith(f".{fmt}")
