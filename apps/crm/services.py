"""Business services and transactional state changes for the CRM module."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core import events
from apps.crm.events import (
    InteractionLogged,
    LeadConverted,
    LeadCreated,
    OpportunityClosedLost,
    OpportunityClosedWon,
    OpportunityCreated,
    OpportunityStageChanged,
    TaskCompleted,
)
from apps.crm.models import (
    CrmTask,
    Interaction,
    InteractionType,
    Lead,
    LeadSource,
    LeadStatus,
    Opportunity,
    OpportunityStatus,
    Pipeline,
    Stage,
    Tag,
    TaskPriority,
    TaskStatus,
)
from apps.customers import services as customers_services
from apps.customers.models import Customer
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")


# =============================================================================
# 1. Pipeline & Stage Services
# =============================================================================


@transaction.atomic
def create_pipeline(
    *,
    organization: Organization,
    name: str,
    code: str,
    description: str = "",
    is_default: bool = False,
    actor: Any = None,
) -> Pipeline:
    """Create a new sales pipeline."""
    if is_default:
        Pipeline.all_tenants.filter(organization=organization, is_default=True).update(is_default=False)

    pipeline = Pipeline.all_tenants.create(
        organization=organization,
        name=name,
        code=code,
        description=description,
        is_default=is_default,
        created_by=actor,
    )
    return pipeline


@transaction.atomic
def create_stage(
    *,
    organization: Organization,
    pipeline: Pipeline,
    name: str,
    code: str,
    order: int = 0,
    probability_percent: int = 10,
    is_won: bool = False,
    is_lost: bool = False,
    actor: Any = None,
) -> Stage:
    """Create a distinct stage in a sales pipeline."""
    stage = Stage.all_tenants.create(
        organization=organization,
        pipeline=pipeline,
        name=name,
        code=code,
        order=order,
        probability_percent=probability_percent,
        is_won=is_won,
        is_lost=is_lost,
        created_by=actor,
    )
    return stage


@transaction.atomic
def seed_default_pipeline(
    *,
    organization: Organization,
    actor: Any = None,
) -> Pipeline:
    """Idempotently seed the standard sales pipeline with default stages."""
    pipeline = Pipeline.all_tenants.filter(organization=organization, code="standard").first()
    if pipeline is None:
        pipeline = create_pipeline(
            organization=organization,
            name="Standard Sales Pipeline",
            code="standard",
            description="Default B2B consultative sales process",
            is_default=True,
            actor=actor,
        )

    default_stages = [
        ("New Lead", "new-lead", 1, 10, False, False),
        ("Contacted", "contacted", 2, 25, False, False),
        ("Meeting / Demo", "demo", 3, 50, False, False),
        ("Proposal Sent", "proposal", 4, 75, False, False),
        ("Negotiation", "negotiation", 5, 90, False, False),
        ("Closed Won", "closed-won", 6, 100, True, False),
        ("Closed Lost", "closed-lost", 7, 0, False, True),
    ]

    for name, code, order, prob, is_won, is_lost in default_stages:
        Stage.all_tenants.get_or_create(
            organization=organization,
            pipeline=pipeline,
            code=code,
            defaults={
                "name": name,
                "order": order,
                "probability_percent": prob,
                "is_won": is_won,
                "is_lost": is_lost,
                "created_by": actor,
            },
        )

    return pipeline


# =============================================================================
# 2. Tag Services
# =============================================================================


@transaction.atomic
def get_or_create_tag(
    *,
    organization: Organization,
    name: str,
    color: str = "#6366f1",
) -> Tag:
    """Get or create a tag for an organization."""
    tag, _ = Tag.all_tenants.get_or_create(
        organization=organization,
        name=name.strip(),
        defaults={"color": color},
    )
    return tag


def _apply_tags(instance: Any, organization: Organization, tag_names: list[str] | None) -> None:
    if tag_names is not None:
        tags = [get_or_create_tag(organization=organization, name=t) for t in tag_names if t.strip()]
        instance.tags.set(tags)


# =============================================================================
# 3. Lead Services
# =============================================================================


@transaction.atomic
def create_lead(
    *,
    organization: Organization,
    first_name: str,
    last_name: str = "",
    company_name: str = "",
    email: str = "",
    phone: str = "",
    title: str = "",
    source: str = LeadSource.WEBSITE,
    status: str = LeadStatus.NEW,
    estimated_value: Decimal = DECIMAL_ZERO,
    assigned_to: Any = None,
    notes: str = "",
    tag_names: list[str] | None = None,
    actor: Any = None,
) -> Lead:
    """Create a new prospective sales lead."""
    lead = Lead.all_tenants.create(
        organization=organization,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        company_name=company_name.strip(),
        email=email.strip().lower(),
        phone=phone.strip(),
        title=title.strip(),
        source=source,
        status=status,
        estimated_value=estimated_value,
        assigned_to=assigned_to,
        notes=notes,
        created_by=actor,
    )
    _apply_tags(lead, organization, tag_names)

    events.publish(
        LeadCreated(
            organization_id=organization.pk,
            lead_id=lead.pk,
            public_id=str(lead.public_id),
            company_name=lead.company_name,
            source=lead.source,
        )
    )
    return lead


@transaction.atomic
def update_lead(
    *,
    organization: Organization,
    lead: Lead,
    first_name: str | None = None,
    last_name: str | None = None,
    company_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    title: str | None = None,
    source: str | None = None,
    status: str | None = None,
    estimated_value: Decimal | None = None,
    assigned_to: Any = None,
    update_assigned_to: bool = False,
    notes: str | None = None,
    tag_names: list[str] | None = None,
    actor: Any = None,
) -> Lead:
    """Update lead details."""
    target_lead = Lead.all_tenants.select_for_update().get(pk=lead.pk, organization=organization)
    update_fields = ["updated_at"]

    if first_name is not None:
        target_lead.first_name = first_name.strip()
        update_fields.append("first_name")
    if last_name is not None:
        target_lead.last_name = last_name.strip()
        update_fields.append("last_name")
    if company_name is not None:
        target_lead.company_name = company_name.strip()
        update_fields.append("company_name")
    if email is not None:
        target_lead.email = email.strip().lower()
        update_fields.append("email")
    if phone is not None:
        target_lead.phone = phone.strip()
        update_fields.append("phone")
    if title is not None:
        target_lead.title = title.strip()
        update_fields.append("title")
    if source is not None:
        target_lead.source = source
        update_fields.append("source")
    if status is not None:
        target_lead.status = status
        update_fields.append("status")
    if estimated_value is not None:
        target_lead.estimated_value = estimated_value
        update_fields.append("estimated_value")
    if update_assigned_to:
        target_lead.assigned_to = assigned_to
        update_fields.append("assigned_to")
    if notes is not None:
        target_lead.notes = notes
        update_fields.append("notes")

    target_lead.save(update_fields=update_fields)
    _apply_tags(target_lead, organization, tag_names)
    return target_lead


# =============================================================================
# 4. Opportunity Services
# =============================================================================


@transaction.atomic
def create_opportunity(
    *,
    organization: Organization,
    title: str,
    pipeline: Pipeline,
    stage: Stage,
    customer: Customer | None = None,
    lead: Lead | None = None,
    expected_value: Decimal = DECIMAL_ZERO,
    currency: str = "USD",
    probability_percent: int | None = None,
    expected_close_date: datetime.date | None = None,
    assigned_to: Any = None,
    notes: str = "",
    tag_names: list[str] | None = None,
    actor: Any = None,
) -> Opportunity:
    """Create a new commercial sales deal."""
    prob = probability_percent if probability_percent is not None else stage.probability_percent
    status = OpportunityStatus.OPEN
    actual_close_date: datetime.date | None = None

    if stage.is_won:
        status = OpportunityStatus.WON
        actual_close_date = timezone.now().date()
    elif stage.is_lost:
        status = OpportunityStatus.LOST
        actual_close_date = timezone.now().date()

    opp = Opportunity.all_tenants.create(
        organization=organization,
        title=title.strip(),
        pipeline=pipeline,
        stage=stage,
        customer=customer,
        lead=lead,
        expected_value=expected_value,
        currency=currency.upper(),
        probability_percent=prob,
        expected_close_date=expected_close_date,
        actual_close_date=actual_close_date,
        status=status,
        assigned_to=assigned_to,
        notes=notes,
        created_by=actor,
    )
    _apply_tags(opp, organization, tag_names)

    events.publish(
        OpportunityCreated(
            organization_id=organization.pk,
            opportunity_id=opp.pk,
            public_id=str(opp.public_id),
            title=opp.title,
            expected_value=str(opp.expected_value),
            stage_id=stage.pk,
        )
    )
    return opp


@transaction.atomic
def convert_lead_to_customer(
    *,
    organization: Organization,
    lead: Lead,
    actor: Any,
    create_deal: bool = True,
    pipeline: Pipeline | None = None,
    deal_title: str = "",
    **kwargs: Any,
) -> tuple[Customer, Opportunity | None]:
    """Convert a qualified lead into an official customer account and optional sales deal."""
    target_lead = Lead.all_tenants.select_for_update().get(pk=lead.pk, organization=organization)
    if target_lead.status == LeadStatus.CONVERTED:
        raise ValidationError(_("This lead has already been converted."))

    should_create_deal = kwargs.get("create_opportunity", create_deal)

    customer_name = target_lead.company_name or f"{target_lead.first_name} {target_lead.last_name}".strip()
    if not customer_name:
        customer_name = target_lead.email or f"Customer-{target_lead.pk}"

    customer = customers_services.create_customer(
        organization=organization,
        name=customer_name,
        email=target_lead.email,
        phone=target_lead.phone,
        notes=f"Converted from Lead #{target_lead.pk} on {timezone.now().date()}",
        actor=actor,
    )

    opp: Opportunity | None = None
    if should_create_deal:
        pipe = pipeline or seed_default_pipeline(organization=organization)
        first_stage = (
            Stage.all_tenants.filter(organization=organization, pipeline=pipe, is_won=False, is_lost=False)
            .order_by("order")
            .first()
        )
        if first_stage is None:
            first_stage = create_stage(
                organization=organization,
                pipeline=pipe,
                name="Initial Qualification",
                code="qual",
                order=1,
            )

        title = deal_title or f"Deal with {customer_name}"
        opp = create_opportunity(
            organization=organization,
            title=title,
            pipeline=pipe,
            stage=first_stage,
            customer=customer,
            lead=target_lead,
            expected_value=target_lead.estimated_value,
            assigned_to=target_lead.assigned_to,
            actor=actor,
        )

    # Link all existing interactions and tasks to the new customer
    Interaction.all_tenants.filter(organization=organization, lead=target_lead).update(customer=customer)
    CrmTask.all_tenants.filter(organization=organization, lead=target_lead).update(customer=customer)

    target_lead.status = LeadStatus.CONVERTED
    target_lead.converted_customer = customer
    target_lead.converted_at = timezone.now()
    target_lead.save(update_fields=["status", "converted_customer", "converted_at", "updated_at"])

    events.publish(
        LeadConverted(
            organization_id=organization.pk,
            lead_id=target_lead.pk,
            customer_id=customer.pk,
            opportunity_id=opp.pk if opp else None,
        )
    )
    return customer, opp


@transaction.atomic
def move_opportunity_stage(
    *,
    organization: Organization,
    opportunity: Opportunity,
    stage: Stage,
    actor: Any = None,
) -> Opportunity:
    """Transition an opportunity to a new pipeline stage and adjust status/probabilities."""
    target_opp = Opportunity.all_tenants.select_for_update().get(pk=opportunity.pk, organization=organization)
    old_stage_id = target_opp.stage_id

    target_opp.stage = stage
    target_opp.probability_percent = stage.probability_percent
    update_fields = ["stage", "probability_percent", "status", "actual_close_date", "updated_at"]

    if stage.is_won:
        target_opp.status = OpportunityStatus.WON
        target_opp.actual_close_date = timezone.now().date()
        target_opp.save(update_fields=update_fields)
        events.publish(
            OpportunityClosedWon(
                organization_id=organization.pk,
                opportunity_id=target_opp.pk,
                actual_value=str(target_opp.expected_value),
            )
        )
    elif stage.is_lost:
        target_opp.status = OpportunityStatus.LOST
        target_opp.actual_close_date = timezone.now().date()
        target_opp.save(update_fields=update_fields)
        events.publish(
            OpportunityClosedLost(
                organization_id=organization.pk,
                opportunity_id=target_opp.pk,
                loss_reason=target_opp.loss_reason,
            )
        )
    else:
        target_opp.status = OpportunityStatus.OPEN
        target_opp.actual_close_date = None
        target_opp.save(update_fields=update_fields)

    events.publish(
        OpportunityStageChanged(
            organization_id=organization.pk,
            opportunity_id=target_opp.pk,
            old_stage_id=old_stage_id,
            new_stage_id=stage.pk,
            new_probability=target_opp.probability_percent,
        )
    )
    return target_opp


@transaction.atomic
def close_opportunity(
    *,
    organization: Organization,
    opportunity: Opportunity,
    won: bool,
    loss_reason: str = "",
    actor: Any = None,
) -> Opportunity:
    """Directly close an opportunity as won or lost."""
    target_opp = Opportunity.all_tenants.select_for_update().get(pk=opportunity.pk, organization=organization)
    target_pipeline = target_opp.pipeline

    if won:
        won_stage = target_pipeline.stages.filter(is_won=True).first()
        if won_stage:
            target_opp.stage = won_stage
        target_opp.status = OpportunityStatus.WON
        target_opp.probability_percent = 100
        target_opp.actual_close_date = timezone.now().date()
        target_opp.save(
            update_fields=["stage", "status", "probability_percent", "actual_close_date", "updated_at"]
        )
        events.publish(
            OpportunityClosedWon(
                organization_id=organization.pk,
                opportunity_id=target_opp.pk,
                actual_value=str(target_opp.expected_value),
            )
        )
    else:
        lost_stage = target_pipeline.stages.filter(is_lost=True).first()
        if lost_stage:
            target_opp.stage = lost_stage
        target_opp.status = OpportunityStatus.LOST
        target_opp.probability_percent = 0
        target_opp.loss_reason = loss_reason
        target_opp.actual_close_date = timezone.now().date()
        target_opp.save(
            update_fields=[
                "stage",
                "status",
                "probability_percent",
                "loss_reason",
                "actual_close_date",
                "updated_at",
            ]
        )
        events.publish(
            OpportunityClosedLost(
                organization_id=organization.pk,
                opportunity_id=target_opp.pk,
                loss_reason=loss_reason,
            )
        )

    return target_opp


# =============================================================================
# 5. Activity: Interaction Services
# =============================================================================


@transaction.atomic
def log_interaction(
    *,
    organization: Organization,
    summary: str,
    type: str = InteractionType.NOTE,
    details: str = "",
    customer: Customer | None = None,
    lead: Lead | None = None,
    opportunity: Opportunity | None = None,
    occurred_at: datetime.datetime | None = None,
    performed_by: Any = None,
    actor: Any = None,
) -> Interaction:
    """Log an interaction touchpoint across leads, customers, or deals."""
    if not customer and not lead and not opportunity:
        raise ValidationError(_("An interaction must relate to at least a customer, lead, or opportunity."))

    interaction = Interaction.all_tenants.create(
        organization=organization,
        type=type,
        summary=summary.strip(),
        details=details,
        customer=customer,
        lead=lead,
        opportunity=opportunity,
        occurred_at=occurred_at or timezone.now(),
        performed_by=performed_by or actor,
        created_by=actor,
    )

    events.publish(
        InteractionLogged(
            organization_id=organization.pk,
            interaction_id=interaction.pk,
            type=interaction.type,
            summary=interaction.summary,
        )
    )
    return interaction


# =============================================================================
# 6. Activity: Task Services
# =============================================================================


@transaction.atomic
def create_crm_task(
    *,
    organization: Organization,
    title: str,
    description: str = "",
    due_date: datetime.date | None = None,
    priority: str = TaskPriority.MEDIUM,
    assigned_to: Any = None,
    customer: Customer | None = None,
    lead: Lead | None = None,
    opportunity: Opportunity | None = None,
    actor: Any = None,
) -> CrmTask:
    """Create a sales task or scheduled action."""
    task = CrmTask.all_tenants.create(
        organization=organization,
        title=title.strip(),
        description=description,
        due_date=due_date,
        priority=priority,
        status=TaskStatus.PENDING,
        assigned_to=assigned_to,
        customer=customer,
        lead=lead,
        opportunity=opportunity,
        created_by=actor,
    )
    return task


@transaction.atomic
def complete_crm_task(
    *,
    organization: Organization,
    task: CrmTask,
    actor: Any,
) -> CrmTask:
    """Mark a CRM task as completed."""
    target_task = CrmTask.all_tenants.select_for_update().get(pk=task.pk, organization=organization)
    target_task.status = TaskStatus.COMPLETED
    target_task.completed_at = timezone.now()
    target_task.completed_by = actor
    target_task.save(update_fields=["status", "completed_at", "completed_by", "updated_at"])

    events.publish(
        TaskCompleted(
            organization_id=organization.pk,
            task_id=target_task.pk,
            title=target_task.title,
        )
    )
    return target_task


@transaction.atomic
def cancel_crm_task(
    *,
    organization: Organization,
    task: CrmTask,
    actor: Any = None,
) -> CrmTask:
    """Cancel a pending CRM task."""
    target_task = CrmTask.all_tenants.select_for_update().get(pk=task.pk, organization=organization)
    target_task.status = TaskStatus.CANCELLED
    target_task.save(update_fields=["status", "updated_at"])
    return target_task
