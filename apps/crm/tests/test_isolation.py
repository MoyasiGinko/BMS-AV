"""Multi-tenant isolation and data leakage prevention tests for the CRM module."""

from decimal import Decimal

import pytest

from apps.core.tenant_context import tenant_context
from apps.crm import selectors, services
from apps.crm.models import (
    CrmTask,
    Interaction,
    Lead,
    Opportunity,
    Pipeline,
    Stage,
)
from apps.customers import services as customers_services
from apps.tenancy.models import Organization


@pytest.fixture
def org_a() -> Organization:
    return Organization.objects.create(name="Tenant Alpha CRM", slug="tenant-alpha-crm")


@pytest.fixture
def org_b() -> Organization:
    return Organization.objects.create(name="Tenant Beta CRM", slug="tenant-beta-crm")


@pytest.mark.django_db
class TestCrmTenantIsolation:
    def test_lead_scoped_querysets(self, org_a: Organization, org_b: Organization) -> None:
        lead_a = services.create_lead(
            organization=org_a,
            first_name="Alpha",
            company_name="Alpha Corp",
        )
        lead_b = services.create_lead(
            organization=org_b,
            first_name="Beta",
            company_name="Beta Corp",
        )

        with tenant_context(org_a):
            qs_a = Lead.objects.all()
            assert lead_a in qs_a
            assert lead_b not in qs_a
            assert selectors.list_leads(organization=org_a).filter(pk=lead_b.pk).exists() is False

        with tenant_context(org_b):
            qs_b = Lead.objects.all()
            assert lead_b in qs_b
            assert lead_a not in qs_b
            assert selectors.list_leads(organization=org_b).filter(pk=lead_a.pk).exists() is False

    def test_pipeline_and_opportunity_isolation(self, org_a: Organization, org_b: Organization) -> None:
        pipe_a = services.seed_default_pipeline(organization=org_a)
        pipe_b = services.seed_default_pipeline(organization=org_b)

        cust_a = customers_services.create_customer(organization=org_a, name="Cust A")
        cust_b = customers_services.create_customer(organization=org_b, name="Cust B")

        stage_a = Stage.all_tenants.get(organization=org_a, pipeline=pipe_a, code="new-lead")
        stage_b = Stage.all_tenants.get(organization=org_b, pipeline=pipe_b, code="new-lead")

        opp_a = services.create_opportunity(
            organization=org_a,
            title="Deal A",
            pipeline=pipe_a,
            stage=stage_a,
            customer=cust_a,
            expected_value=Decimal("1000.0000"),
        )
        opp_b = services.create_opportunity(
            organization=org_b,
            title="Deal B",
            pipeline=pipe_b,
            stage=stage_b,
            customer=cust_b,
            expected_value=Decimal("2000.0000"),
        )

        with tenant_context(org_a):
            assert Opportunity.objects.filter(pk=opp_b.pk).exists() is False
            assert Pipeline.objects.filter(pk=pipe_b.pk).exists() is False
            kanban_a = selectors.get_pipeline_kanban(organization=org_a, pipeline_id=pipe_a.pk)
            assert kanban_a["total_deals"] == 1
            assert kanban_a["total_pipeline_value"] == Decimal("1000.0000")

        with tenant_context(org_b):
            assert Opportunity.objects.filter(pk=opp_a.pk).exists() is False
            assert Pipeline.objects.filter(pk=pipe_a.pk).exists() is False
            kanban_b = selectors.get_pipeline_kanban(organization=org_b, pipeline_id=pipe_b.pk)
            assert kanban_b["total_deals"] == 1
            assert kanban_b["total_pipeline_value"] == Decimal("2000.0000")

    def test_customer_360_cross_tenant_isolation(self, org_a: Organization, org_b: Organization) -> None:
        cust_b = customers_services.create_customer(organization=org_b, name="Private Beta Client")

        # Querying tenant B customer from tenant A context yields None
        data = selectors.get_customer_360(organization=org_a, customer_id=cust_b.pk)
        assert data is None

    def test_interactions_and_tasks_isolation(self, org_a: Organization, org_b: Organization) -> None:
        lead_a = services.create_lead(organization=org_a, first_name="A")
        lead_b = services.create_lead(organization=org_b, first_name="B")

        int_a = services.log_interaction(
            organization=org_a,
            summary="Confidential call A",
            lead=lead_a,
        )
        int_b = services.log_interaction(
            organization=org_b,
            summary="Confidential call B",
            lead=lead_b,
        )

        task_a = services.create_crm_task(organization=org_a, title="Task A", lead=lead_a)
        task_b = services.create_crm_task(organization=org_b, title="Task B", lead=lead_b)

        with tenant_context(org_a):
            assert Interaction.objects.filter(pk=int_b.pk).exists() is False
            assert CrmTask.objects.filter(pk=task_b.pk).exists() is False

        with tenant_context(org_b):
            assert Interaction.objects.filter(pk=int_a.pk).exists() is False
            assert CrmTask.objects.filter(pk=task_a.pk).exists() is False
