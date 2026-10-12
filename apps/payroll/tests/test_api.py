"""REST API integration tests for Payroll endpoints."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.hr.models import Employee
from apps.payroll.models import (
    EmployeeSalaryAssignment,
)
from apps.tenancy.models import Membership, Organization


@pytest.fixture
def api_client(user: Any, org: Organization, membership: Membership) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    client.defaults["HTTP_X_ORGANIZATION_ID"] = str(org.pk)
    return client


@pytest.mark.django_db
def test_payroll_api_components_and_structures(
    api_client: APIClient,
    org: Organization,
) -> None:
    # 1. Components
    resp = api_client.post(
        "/api/v1/payroll/components/",
        data={
            "name": "Overtime Allowance",
            "code": "OT",
            "component_type": "earning",
            "is_taxable": True,
            "is_active": True,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    comp_pub_id = resp.data["public_id"]
    assert comp_pub_id is not None

    resp = api_client.get("/api/v1/payroll/components/")
    assert resp.status_code == status.HTTP_200_OK

    # 2. Structures
    resp = api_client.post(
        "/api/v1/payroll/structures/",
        data={
            "name": "Engineering Structure",
            "code": "ENG-STRUCT",
            "description": "Tech team package",
            "is_active": True,
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED

    resp = api_client.get("/api/v1/payroll/structures/")
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_payroll_api_runs_lifecycle(
    api_client: APIClient,
    org: Organization,
    org_accounts: dict[str, Any],
    employee: Employee,
    salary_assignment: EmployeeSalaryAssignment,
) -> None:
    # 1. Create run
    resp = api_client.post(
        "/api/v1/payroll/runs/",
        data={
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
            "payment_date": "2026-05-31",
            "notes": "May 2026 Run",
        },
    )
    assert resp.status_code == status.HTTP_201_CREATED
    run_pub_id = resp.data["public_id"]
    assert resp.data["status"] == "draft"
    assert resp.data["payslips_count"] == 1

    # 2. Review action
    resp = api_client.post(f"/api/v1/payroll/runs/{run_pub_id}/review/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["status"] == "reviewed"

    # 3. Approve action
    resp = api_client.post(f"/api/v1/payroll/runs/{run_pub_id}/approve/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["status"] == "approved"
    assert resp.data["journal_entry_number"] is not None

    # 4. Pay action
    resp = api_client.post(
        f"/api/v1/payroll/runs/{run_pub_id}/pay/",
        data={"payment_account": "bank"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["status"] == "paid"
    assert resp.data["payment_journal_entry_number"] is not None

    # 5. Payslip list and PDF action
    resp = api_client.get("/api/v1/payroll/payslips/")
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.data["results"]) == 1
    slip_pub_id = resp.data["results"][0]["public_id"]

    pdf_resp = api_client.get(f"/api/v1/payroll/payslips/{slip_pub_id}/pdf/")
    assert pdf_resp.status_code == status.HTTP_200_OK
    assert pdf_resp["Content-Type"] == "application/pdf"

    # 6. Cancel action
    resp = api_client.post(
        f"/api/v1/payroll/runs/{run_pub_id}/cancel/",
        data={"reason": "Audit request"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["status"] == "cancelled"
