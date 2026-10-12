"""Comprehensive unit tests for CRM services."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import OutboxEvent
from apps.core.tenant_context import tenant_context
from apps.crm import services
from apps.crm.models import (
    CrmTask,
    Interaction,
    InteractionType,
    LeadSource,
    LeadStatus,
    OpportunityStatus,
    Stage,
    TaskPriority,
    TaskStatus,
)
from apps.customers import services as customers_services
from apps.tenancy.models import Organization

User = get_user_model()


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="CRM Test Org", slug="crm-test-org")


@pytest.fixture(autouse=True)
def activate_tenant(org: Organization) -> Any:
    with tenant_context(org):
        yield


@pytest.fixture
def user(org: Organization) -> Any:
    u = User.objects.create_user(email="crm@example.com", password="Password123!")
    return u


@pytest.mark.django_db
class TestCrmPipelineAndStageServices:
    def test_create_pipeline_and_stages(self, org: Organization, user: Any) -> None:
        pipeline = services.create_pipeline(
            organization=org,
            name="Enterprise Funnel",
            code="enterprise",
            description="Enterprise deal stages",
            is_default=True,
            actor=user,
        )
        assert pipeline.pk is not None
        assert pipeline.organization == org
        assert pipeline.is_default is True

        stage1 = services.create_stage(
            organization=org,
            pipeline=pipeline,
            name="Discovery",
            code="discovery",
            order=1,
            probability_percent=20,
            actor=user,
        )
        assert stage1.pk is not None
        assert stage1.pipeline == pipeline
        assert stage1.probability_percent == 20
        assert stage1.is_won is False

    def test_seed_default_pipeline_is_idempotent(self, org: Organization, user: Any) -> None:
        p1 = services.seed_default_pipeline(organization=org, actor=user)
        assert Stage.all_tenants.filter(organization=org, pipeline=p1).count() == 7
        assert p1.is_default is True

        # Re-running seed does not duplicate stages or pipeline
        p2 = services.seed_default_pipeline(organization=org, actor=user)
        assert p1.pk == p2.pk
        assert Stage.all_tenants.filter(organization=org, pipeline=p2).count() == 7


@pytest.mark.django_db
class TestCrmLeadServices:
    def test_create_and_update_lead(self, org: Organization, user: Any) -> None:
        lead = services.create_lead(
            organization=org,
            first_name="Jane",
            last_name="Doe",
            company_name="Acme Tech",
            email="jane@acme.com",
            phone="+123456789",
            source=LeadSource.WEBSITE,
            estimated_value=Decimal("15000.0000"),
            assigned_to=user,
            tag_names=["Inbound", "High-Priority"],
            actor=user,
        )
        assert lead.pk is not None
        assert lead.company_name == "Acme Tech"
        assert lead.estimated_value == Decimal("15000.0000")
        assert lead.tags.count() == 2

        # Check outbox event
        assert OutboxEvent.objects.filter(event_type="crm.lead_created").exists()

        # Update lead
        updated = services.update_lead(
            organization=org,
            lead=lead,
            status=LeadStatus.QUALIFIED,
            estimated_value=Decimal("20000.0000"),
            tag_names=["Inbound", "Enterprise"],
            actor=user,
        )
        assert updated.status == LeadStatus.QUALIFIED
        assert updated.estimated_value == Decimal("20000.0000")
        assert updated.tags.filter(name="Enterprise").exists()

    def test_convert_lead_to_customer_with_opportunity(self, org: Organization, user: Any) -> None:
        lead = services.create_lead(
            organization=org,
            first_name="Robert",
            last_name="Smith",
            company_name="Apex Global",
            email="robert@apex.com",
            estimated_value=Decimal("50000.0000"),
            actor=user,
        )

        # Log an interaction and task on the lead
        services.log_interaction(
            organization=org,
            summary="Initial qualification call",
            lead=lead,
            actor=user,
        )
        services.create_crm_task(
            organization=org,
            title="Prepare discovery proposal",
            lead=lead,
            actor=user,
        )

        customer, opp = services.convert_lead_to_customer(
            organization=org,
            lead=lead,
            actor=user,
            create_opportunity=True,
        )

        assert customer.pk is not None
        assert customer.name == "Apex Global"
        assert customer.email == "robert@apex.com"

        assert opp is not None
        assert opp.customer == customer
        assert opp.expected_value == Decimal("50000.0000")
        assert opp.lead == lead

        # Check lead is marked converted
        lead.refresh_from_db()
        assert lead.status == LeadStatus.CONVERTED
        assert lead.converted_customer == customer
        assert lead.converted_at is not None

        # Verify interactions and tasks re-linked to customer
        assert Interaction.all_tenants.filter(customer=customer).count() == 1
        assert CrmTask.all_tenants.filter(customer=customer).count() == 1

        # Check outbox event
        assert OutboxEvent.objects.filter(event_type="crm.lead_converted").exists()

    def test_convert_lead_twice_raises_validation_error(self, org: Organization, user: Any) -> None:
        lead = services.create_lead(
            organization=org,
            first_name="Double",
            company_name="Convert Inc",
            actor=user,
        )
        services.convert_lead_to_customer(organization=org, lead=lead, actor=user)

        with pytest.raises(ValidationError):
            services.convert_lead_to_customer(organization=org, lead=lead, actor=user)


@pytest.mark.django_db
class TestCrmOpportunityServices:
    def test_create_and_move_opportunity_stages(self, org: Organization, user: Any) -> None:
        pipeline = services.seed_default_pipeline(organization=org, actor=user)
        stage_lead = Stage.all_tenants.get(organization=org, pipeline=pipeline, code="new-lead")
        stage_proposal = Stage.all_tenants.get(organization=org, pipeline=pipeline, code="proposal")
        stage_won = Stage.all_tenants.get(organization=org, pipeline=pipeline, code="closed-won")

        customer = customers_services.create_customer(
            organization=org,
            name="MegaCorp Deals",
            actor=user,
        )

        opp = services.create_opportunity(
            organization=org,
            title="MegaCorp Cloud Migration",
            pipeline=pipeline,
            stage=stage_lead,
            customer=customer,
            expected_value=Decimal("75000.0000"),
            assigned_to=user,
            tag_names=["Enterprise"],
            actor=user,
        )
        assert opp.pk is not None
        assert opp.probability_percent == stage_lead.probability_percent
        assert opp.status == OpportunityStatus.OPEN

        # Move to Proposal
        services.move_opportunity_stage(
            organization=org,
            opportunity=opp,
            stage=stage_proposal,
            actor=user,
        )
        opp.refresh_from_db()
        assert opp.stage == stage_proposal
        assert opp.probability_percent == stage_proposal.probability_percent
        assert opp.status == OpportunityStatus.OPEN

        # Move to Closed Won
        services.move_opportunity_stage(
            organization=org,
            opportunity=opp,
            stage=stage_won,
            actor=user,
        )
        opp.refresh_from_db()
        assert opp.stage == stage_won
        assert opp.status == OpportunityStatus.WON
        assert opp.actual_close_date == timezone.now().date()
        assert OutboxEvent.objects.filter(event_type="crm.opportunity_closed_won").exists()

        # Close directly as lost
        services.close_opportunity(
            organization=org,
            opportunity=opp,
            won=False,
            loss_reason="Budget frozen",
            actor=user,
        )
        opp.refresh_from_db()
        assert opp.status == OpportunityStatus.LOST
        assert opp.loss_reason == "Budget frozen"
        assert OutboxEvent.objects.filter(event_type="crm.opportunity_closed_lost").exists()


@pytest.mark.django_db
class TestCrmInteractionsAndTasks:
    def test_log_interaction_validation(self, org: Organization, user: Any) -> None:
        # Fails if not linked to any entity
        with pytest.raises(ValidationError):
            services.log_interaction(
                organization=org,
                summary="Orphan interaction",
                actor=user,
            )

        lead = services.create_lead(
            organization=org,
            first_name="Active",
            company_name="Interactions Co",
            actor=user,
        )
        interaction = services.log_interaction(
            organization=org,
            summary="Demo meeting held",
            type=InteractionType.MEETING,
            details="Walked through CRM pipeline features.",
            lead=lead,
            actor=user,
        )
        assert interaction.pk is not None
        assert interaction.type == InteractionType.MEETING
        assert OutboxEvent.objects.filter(event_type="crm.interaction_logged").exists()

    def test_crm_task_completion(self, org: Organization, user: Any) -> None:
        task = services.create_crm_task(
            organization=org,
            title="Follow up on pricing contract",
            priority=TaskPriority.HIGH,
            actor=user,
        )
        assert task.status == TaskStatus.PENDING

        completed = services.complete_crm_task(
            organization=org,
            task=task,
            actor=user,
        )
        assert completed.status == TaskStatus.COMPLETED
        assert completed.completed_at is not None
        assert OutboxEvent.objects.filter(event_type="crm.task_completed").exists()
