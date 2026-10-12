"""Integration tests for CRM REST API endpoints."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import seed_default_plans
from apps.crm import services
from apps.crm.models import LeadSource, LeadStatus, Stage
from apps.customers import services as customers_services
from apps.tenancy.services import provision_organization


@pytest.fixture
def crm_api_setup(db: None) -> dict[str, Any]:
    seed_default_plans()

    admin_user = User.objects.create_user(email="crm_api_admin@example.com", password="Password123!")
    org = provision_organization(name="CRM API Org", slug="crm-api-org", owner=admin_user, plan="growth")

    pipeline = services.seed_default_pipeline(organization=org, actor=admin_user)

    lead = services.create_lead(
        organization=org,
        first_name="Zaphod",
        last_name="Beeblebrox",
        company_name="Heart of Gold Corp",
        email="zaphod@beeblebrox.galaxy",
        source=LeadSource.WEBSITE,
        status=LeadStatus.NEW,
        estimated_value=Decimal("85000.0000"),
        actor=admin_user,
    )

    customer = customers_services.create_customer(
        organization=org,
        name="Sirius Cybernetics",
        actor=admin_user,
    )

    opp = services.create_opportunity(
        organization=org,
        title="Infinite Improbability Drive Deal",
        pipeline=pipeline,
        stage=Stage.all_tenants.filter(organization=org, pipeline=pipeline).first(),
        customer=customer,
        expected_value=Decimal("120000.0000"),
        actor=admin_user,
    )

    client = APIClient()
    client.force_authenticate(user=admin_user)

    return {
        "client": client,
        "admin_user": admin_user,
        "org": org,
        "pipeline": pipeline,
        "lead": lead,
        "customer": customer,
        "opp": opp,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
class TestCrmAPI:
    def test_list_and_retrieve_pipelines(self, crm_api_setup: dict[str, Any]) -> None:
        client: APIClient = crm_api_setup["client"]
        headers: dict[str, str] = crm_api_setup["headers"]
        pipeline = crm_api_setup["pipeline"]

        resp = client.get("/api/v1/crm/pipelines/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data["results"]) >= 1

        detail_resp = client.get(f"/api/v1/crm/pipelines/{pipeline.public_id}/", **headers)
        assert detail_resp.status_code == status.HTTP_200_OK
        detail_data = detail_resp.json()
        assert detail_data["name"] == pipeline.name
        assert len(detail_data["stages"]) == 7

    def test_create_and_list_leads(self, crm_api_setup: dict[str, Any]) -> None:
        client: APIClient = crm_api_setup["client"]
        headers: dict[str, str] = crm_api_setup["headers"]

        post_data = {
            "first_name": "Tricia",
            "last_name": "McMillan",
            "company_name": "Sub-Etha Astrophysics",
            "email": "trillian@galaxy.org",
            "phone": "+987654321",
            "source": "referral",
            "status": "new",
            "estimated_value": "45000.00",
            "tags": ["Astro", "Priority"],
        }
        create_resp = client.post("/api/v1/crm/leads/", post_data, format="json", **headers)
        assert create_resp.status_code == status.HTTP_201_CREATED
        created = create_resp.json()
        assert created["first_name"] == "Tricia"
        assert created["company_name"] == "Sub-Etha Astrophysics"

        list_resp = client.get("/api/v1/crm/leads/", **headers)
        assert list_resp.status_code == status.HTTP_200_OK
        assert len(list_resp.json()["results"]) >= 2

    def test_convert_lead_api(self, crm_api_setup: dict[str, Any]) -> None:
        client: APIClient = crm_api_setup["client"]
        headers: dict[str, str] = crm_api_setup["headers"]
        lead = crm_api_setup["lead"]

        conv_resp = client.post(
            f"/api/v1/crm/leads/{lead.public_id}/convert/",
            {"create_opportunity": True, "deal_title": "Custom Deal Name"},
            format="json",
            **headers,
        )
        assert conv_resp.status_code == status.HTTP_200_OK
        data = conv_resp.json()
        assert "customer_id" in data
        assert data["customer_name"] == "Heart of Gold Corp"
        assert data["opportunity_id"] is not None

    def test_opportunity_move_stage_api(self, crm_api_setup: dict[str, Any]) -> None:
        client: APIClient = crm_api_setup["client"]
        headers: dict[str, str] = crm_api_setup["headers"]
        opp = crm_api_setup["opp"]
        pipeline = crm_api_setup["pipeline"]

        target_stage = list(
            Stage.all_tenants.filter(organization=crm_api_setup["org"], pipeline=pipeline).order_by("order")
        )[2]
        move_resp = client.post(
            f"/api/v1/crm/opportunities/{opp.public_id}/move-stage/",
            {"stage_id": target_stage.pk},
            format="json",
            **headers,
        )
        assert move_resp.status_code == status.HTTP_200_OK
        opp.refresh_from_db()
        assert opp.stage == target_stage

    def test_customer_360_api(self, crm_api_setup: dict[str, Any]) -> None:
        client: APIClient = crm_api_setup["client"]
        headers: dict[str, str] = crm_api_setup["headers"]
        customer = crm_api_setup["customer"]

        resp = client.get(f"/api/v1/crm/customer-360/{customer.public_id}/", **headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["customer"]["name"] == "Sirius Cybernetics"
        assert len(data["opportunities"]) >= 1

    def test_create_interaction_and_task_api(self, crm_api_setup: dict[str, Any]) -> None:
        client: APIClient = crm_api_setup["client"]
        headers: dict[str, str] = crm_api_setup["headers"]
        lead = crm_api_setup["lead"]

        # Interaction
        int_resp = client.post(
            "/api/v1/crm/interactions/",
            {
                "type": "call",
                "summary": "Introductory video call",
                "details": "Discussed system specifications.",
                "lead_id": str(lead.public_id),
            },
            format="json",
            **headers,
        )
        assert int_resp.status_code == status.HTTP_201_CREATED

        # Task
        task_resp = client.post(
            "/api/v1/crm/tasks/",
            {
                "title": "Prepare quote sheet",
                "priority": "high",
                "lead_id": str(lead.public_id),
            },
            format="json",
            **headers,
        )
        assert task_resp.status_code == status.HTTP_201_CREATED
        task_data = task_resp.json()

        # Complete task
        comp_resp = client.post(
            f"/api/v1/crm/tasks/{task_data['public_id']}/complete/",
            {},
            format="json",
            **headers,
        )
        assert comp_resp.status_code == status.HTTP_200_OK
        assert comp_resp.json()["status"] == "completed"
