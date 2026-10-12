"""Unit tests for CRM query selectors, Kanban aggregations, and Customer 360."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model

from apps.core.tenant_context import tenant_context
from apps.crm import selectors, services
from apps.crm.models import InteractionType, LeadSource, LeadStatus, Stage
from apps.customers import services as customers_services
from apps.tenancy.models import Organization

User = get_user_model()


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="Selector Org", slug="selector-org")


@pytest.fixture(autouse=True)
def activate_tenant(org: Organization) -> Any:
    with tenant_context(org):
        yield


@pytest.fixture
def user(org: Organization) -> Any:
    return User.objects.create_user(email="sel@example.com", password="Password123!")


@pytest.mark.django_db
class TestCrmSelectors:
    def test_list_leads_filtering(self, org: Organization, user: Any) -> None:
        services.create_lead(
            organization=org,
            first_name="Alice",
            company_name="Alpha Tech",
            source=LeadSource.WEBSITE,
            status=LeadStatus.NEW,
            actor=user,
        )
        services.create_lead(
            organization=org,
            first_name="Bob",
            company_name="Beta Logistics",
            source=LeadSource.REFERRAL,
            status=LeadStatus.QUALIFIED,
            actor=user,
        )

        all_leads = selectors.list_leads(organization=org)
        assert all_leads.count() == 2

        filtered_status = selectors.list_leads(organization=org, status=LeadStatus.QUALIFIED)
        assert filtered_status.count() == 1
        assert filtered_status.first().first_name == "Bob"

        filtered_search = selectors.list_leads(organization=org, search="Alpha")
        assert filtered_search.count() == 1
        assert filtered_search.first().company_name == "Alpha Tech"

    def test_pipeline_kanban_structure(self, org: Organization, user: Any) -> None:
        pipeline = services.seed_default_pipeline(organization=org, actor=user)
        stage_discovery = Stage.all_tenants.get(organization=org, pipeline=pipeline, code="new-lead")

        customer = customers_services.create_customer(organization=org, name="Kanban Client", actor=user)

        services.create_opportunity(
            organization=org,
            title="Deal A",
            pipeline=pipeline,
            stage=stage_discovery,
            customer=customer,
            expected_value=Decimal("12000.0000"),
            actor=user,
        )
        services.create_opportunity(
            organization=org,
            title="Deal B",
            pipeline=pipeline,
            stage=stage_discovery,
            customer=customer,
            expected_value=Decimal("8000.0000"),
            actor=user,
        )

        kanban = selectors.get_pipeline_kanban(organization=org, pipeline_id=pipeline.pk)
        assert kanban["total_deals"] == 2
        assert kanban["total_pipeline_value"] == Decimal("20000.0000")

        discovery_col = next(c for c in kanban["stages"] if c["stage"].code == "new-lead")
        assert discovery_col["count"] == 2
        assert discovery_col["total_value"] == Decimal("20000.0000")

    def test_customer_360_synthesis(self, org: Organization, user: Any) -> None:
        pipeline = services.seed_default_pipeline(organization=org, actor=user)
        stage = Stage.all_tenants.filter(organization=org, pipeline=pipeline).first()

        customer = customers_services.create_customer(
            organization=org,
            name="Omni Enterprise",
            opening_balance=Decimal("1500.0000"),
            actor=user,
        )

        # Create deal
        services.create_opportunity(
            organization=org,
            title="Omni Retainer",
            pipeline=pipeline,
            stage=stage,
            customer=customer,
            expected_value=Decimal("45000.0000"),
            actor=user,
        )

        # Log touchpoints
        services.log_interaction(
            organization=org,
            summary="Quarterly business review",
            type=InteractionType.MEETING,
            customer=customer,
            actor=user,
        )

        # Schedule task
        services.create_crm_task(
            organization=org,
            title="Send updated rate card",
            customer=customer,
            actor=user,
        )

        c360 = selectors.get_customer_360(organization=org, customer_id=customer.pk)
        assert c360 is not None
        assert c360["customer"] == customer
        assert c360["active_deals_count"] == 1
        assert c360["total_pipeline_value"] == Decimal("45000.0000")
        assert len(c360["interactions"]) == 1
        assert len(c360["tasks"]) == 1
        assert c360["open_ar_balance"] == Decimal("1500.0000")

    def test_inactive_customers_selector(self, org: Organization, user: Any) -> None:
        customer = customers_services.create_customer(
            organization=org,
            name="Dormant Customer",
            actor=user,
        )

        inactive = selectors.get_inactive_customers(organization=org, days_threshold=30)
        assert len(inactive) >= 1
        dormant_item = next(item for item in inactive if item["customer"].pk == customer.pk)
        assert dormant_item["days_inactive"] >= 30
