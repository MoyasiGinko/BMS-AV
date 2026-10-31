"""Web view integration tests for Payroll module."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.hr.models import Employee
from apps.payroll import selectors
from apps.payroll.models import (
    EmployeeSalaryAssignment,
    PayrollRunStatus,
    SalaryStructure,
)
from apps.tenancy.models import Membership, Organization


@pytest.fixture
def auth_client(client: Client, user: Any, org: Organization, membership: Membership) -> Client:
    client.force_login(user)
    session = client.session
    session["organization_id"] = org.pk
    session.save()
    return client


@pytest.mark.django_db
def test_run_views_flow_and_pdf_download(
    auth_client: Client,
    org: Organization,
    org_accounts: dict[str, Any],
    employee: Employee,
    salary_assignment: EmployeeSalaryAssignment,
    user: Any,
) -> None:
    # 1. Run list view
    url = reverse("payroll:run_list")
    resp = auth_client.get(url)
    assert resp.status_code == 200

    # 2. Run create view
    create_url = reverse("payroll:run_create")
    resp = auth_client.get(create_url)
    assert resp.status_code == 200

    resp = auth_client.post(
        create_url,
        data={
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
            "payment_date": "2026-03-31",
            "notes": "March 2026 Run",
        },
    )
    assert resp.status_code == 302

    run = selectors.list_payroll_runs(organization=org).first()
    assert run is not None
    assert run.status == PayrollRunStatus.DRAFT

    # 3. Run detail view
    detail_url = reverse("payroll:run_detail", kwargs={"public_id": run.public_id})
    resp = auth_client.get(detail_url)
    assert resp.status_code == 200
    assert run.number.encode() in resp.content

    # 4. Review action
    review_url = reverse("payroll:run_review", kwargs={"public_id": run.public_id})
    resp = auth_client.post(review_url)
    assert resp.status_code == 302
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.REVIEWED

    # 5. Approve action
    approve_url = reverse("payroll:run_approve", kwargs={"public_id": run.public_id})
    resp = auth_client.post(approve_url)
    assert resp.status_code == 302
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.APPROVED
    assert run.journal_entry is not None

    # 6. Pay action
    pay_url = reverse("payroll:run_pay", kwargs={"public_id": run.public_id})
    resp = auth_client.post(pay_url, data={"payment_account": "bank"})
    assert resp.status_code == 302
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.PAID
    assert run.payment_journal_entry is not None

    # 7. Payslip detail and PDF download
    payslip = run.payslips.first()
    assert payslip is not None

    slip_url = reverse("payroll:payslip_detail", kwargs={"public_id": payslip.public_id})
    resp = auth_client.get(slip_url)
    assert resp.status_code == 200

    pdf_url = reverse("payroll:payslip_pdf", kwargs={"public_id": payslip.public_id})
    pdf_resp = auth_client.get(pdf_url)
    assert pdf_resp.status_code == 200
    assert pdf_resp["Content-Type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")

    # 8. Cancel action
    cancel_url = reverse("payroll:run_cancel", kwargs={"public_id": run.public_id})
    resp = auth_client.post(cancel_url, data={"reason": "Testing cancellation"})
    assert resp.status_code == 302
    run.refresh_from_db()
    assert run.status == PayrollRunStatus.CANCELLED


@pytest.mark.django_db
def test_structure_component_and_assignment_views(
    auth_client: Client,
    org: Organization,
    employee: Employee,
    salary_structure: SalaryStructure,
    user: Any,
) -> None:
    # Component list and create
    comp_list_url = reverse("payroll:component_list")
    resp = auth_client.get(comp_list_url)
    assert resp.status_code == 200

    comp_create_url = reverse("payroll:component_create")
    resp = auth_client.post(
        comp_create_url,
        data={
            "name": "Medical Allowance",
            "code": "MED",
            "component_type": "earning",
            "is_taxable": True,
            "is_active": True,
        },
    )
    assert resp.status_code == 302

    # Structure list and create
    struct_list_url = reverse("payroll:structure_list")
    resp = auth_client.get(struct_list_url)
    assert resp.status_code == 200

    struct_create_url = reverse("payroll:structure_create")
    resp = auth_client.post(
        struct_create_url,
        data={
            "name": "Sales Package",
            "code": "SALES-01",
            "description": "Sales Commission Structure",
            "is_active": True,
        },
    )
    assert resp.status_code == 302

    # Assignment list and create
    assign_list_url = reverse("payroll:assignment_list")
    resp = auth_client.get(assign_list_url)
    assert resp.status_code == 200

    assign_create_url = reverse("payroll:assignment_create")
    resp = auth_client.post(
        assign_create_url,
        data={
            "employee": employee.pk,
            "salary_structure": salary_structure.pk,
            "base_salary": "7500.00",
            "effective_from": "2026-04-01",
            "payment_method": "bank_transfer",
            "is_active": True,
        },
    )
    assert resp.status_code == 302

@pytest.mark.django_db
def test_my_payslips_view_without_and_with_employee(
    auth_client: Client,
    org: Organization,
    employee: Employee,
    user: Any,
) -> None:
    url = reverse("payroll:my_payslips")

    # Case 1: user has no linked Employee record (employee fixture links user by default)
    employee.user = None
    employee.save()

    resp = auth_client.get(url)
    assert resp.status_code == 200
    assert "No employee record is currently linked to your user account." in resp.content.decode()

    # Case 2: user linked to employee
    employee.user = user
    employee.save()

    resp = auth_client.get(url)
    assert resp.status_code == 200
    assert employee.full_name in resp.content.decode()
    assert "No payslips issued yet for your employee account." in resp.content.decode()

