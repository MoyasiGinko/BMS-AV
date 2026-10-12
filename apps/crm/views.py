"""Server-rendered HTMX views for the CRM module."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.permissions import permission_required
from apps.crm import selectors, services
from apps.crm.forms import CrmTaskForm, InteractionForm, LeadForm, OpportunityForm
from apps.crm.models import (
    CrmTask,
    Lead,
    LeadStatus,
    Opportunity,
    Stage,
)
from apps.customers.models import Customer
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


# =============================================================================
# 1. Leads Views
# =============================================================================


@permission_required("crm.view")
def lead_list_view(request: HttpRequest) -> HttpResponse:
    """Lead directory with search, status filtering, and HTMX pagination."""
    org = _get_org(request)
    status_filter = request.GET.get("status", "")
    source_filter = request.GET.get("source", "")
    search = request.GET.get("search", "")

    leads_qs = selectors.list_leads(
        organization=org,
        status=status_filter or None,
        source=source_filter or None,
        search=search,
    )

    paginator = Paginator(leads_qs, 25)
    page_num = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_num)

    context: dict[str, Any] = {
        "page_obj": page_obj,
        "leads": page_obj.object_list,
        "status_filter": status_filter,
        "source_filter": source_filter,
        "search": search,
        "status_choices": LeadStatus.choices,
    }

    if request.headers.get("HX-Request"):
        return render(request, "crm/partials/lead_table_rows.html", context)
    return render(request, "crm/lead_list.html", context)


@permission_required("crm.create")
def lead_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new lead."""
    org = _get_org(request)

    if request.method == "POST":
        form = LeadForm(request.POST, organization=org)
        if form.is_valid():
            tags_raw = form.cleaned_data.get("tags_csv", "")
            tag_names = [t.strip() for t in tags_raw.split(",") if t.strip()]

            lead = services.create_lead(
                organization=org,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                company_name=form.cleaned_data["company_name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                title=form.cleaned_data["title"],
                source=form.cleaned_data["source"],
                status=form.cleaned_data["status"],
                estimated_value=form.cleaned_data["estimated_value"],
                assigned_to=form.cleaned_data["assigned_to"],
                notes=form.cleaned_data["notes"],
                tag_names=tag_names,
                actor=request.user,
            )
            messages.success(request, _("Lead '%(name)s' created.") % {"name": lead})
            return redirect("crm:lead_detail", public_id=lead.public_id)
    else:
        form = LeadForm(organization=org)

    return render(request, "crm/lead_form.html", {"form": form, "title": _("New Lead")})


@permission_required("crm.view")
def lead_detail_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Detailed profile of a lead with interactions and tasks."""
    org = _get_org(request)
    lead = get_object_or_404(Lead.all_tenants, organization=org, public_id=public_id)

    interactions = selectors.list_interactions(organization=org, lead_id=lead.pk)
    tasks = selectors.list_tasks(organization=org, lead_id=lead.pk)

    interaction_form = InteractionForm()
    task_form = CrmTaskForm(organization=org)

    return render(
        request,
        "crm/lead_detail.html",
        {
            "lead": lead,
            "interactions": interactions,
            "tasks": tasks,
            "interaction_form": interaction_form,
            "task_form": task_form,
        },
    )


@permission_required("crm.update")
def lead_edit_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Edit lead information."""
    org = _get_org(request)
    lead = get_object_or_404(Lead.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead, organization=org)
        if form.is_valid():
            tags_raw = form.cleaned_data.get("tags_csv", "")
            tag_names = [t.strip() for t in tags_raw.split(",") if t.strip()]

            services.update_lead(
                organization=org,
                lead=lead,
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                company_name=form.cleaned_data["company_name"],
                email=form.cleaned_data["email"],
                phone=form.cleaned_data["phone"],
                title=form.cleaned_data["title"],
                source=form.cleaned_data["source"],
                status=form.cleaned_data["status"],
                estimated_value=form.cleaned_data["estimated_value"],
                assigned_to=form.cleaned_data["assigned_to"],
                update_assigned_to=True,
                notes=form.cleaned_data["notes"],
                tag_names=tag_names,
                actor=request.user,
            )
            messages.success(request, _("Lead updated successfully."))
            return redirect("crm:lead_detail", public_id=lead.public_id)
    else:
        form = LeadForm(instance=lead, organization=org)

    return render(
        request,
        "crm/lead_form.html",
        {"form": form, "lead": lead, "title": _("Edit Lead")},
    )


@permission_required("crm.update")
def lead_convert_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Convert lead into an active customer account with optional deal creation."""
    org = _get_org(request)
    lead = get_object_or_404(Lead.all_tenants, organization=org, public_id=public_id)

    if request.method == "POST":
        create_deal = request.POST.get("create_opportunity") == "on"
        try:
            customer, opp = services.convert_lead_to_customer(
                organization=org,
                lead=lead,
                actor=request.user,
                create_opportunity=create_deal,
            )
            messages.success(
                request,
                _("Lead successfully converted to customer '%(cust)s'.") % {"cust": customer.name},
            )
            if opp:
                return redirect("crm:opportunity_detail", public_id=opp.public_id)
            return redirect("crm:customer_360", customer_id=customer.pk)
        except ValidationError as e:
            messages.error(request, str(e.message if hasattr(e, "message") else e))
            return redirect("crm:lead_detail", public_id=lead.public_id)

    return render(request, "crm/lead_convert_confirm.html", {"lead": lead})


# =============================================================================
# 2. Pipeline & Opportunities (Kanban)
# =============================================================================


@permission_required("crm.view")
def pipeline_kanban_view(request: HttpRequest) -> HttpResponse:
    """Visual Kanban board for sales opportunities grouped by stage."""
    org = _get_org(request)
    pipeline_code = request.GET.get("pipeline", "")

    pipeline = selectors.get_pipeline(organization=org, code=pipeline_code or None)
    if not pipeline:
        pipeline = services.seed_default_pipeline(organization=org, actor=request.user)

    kanban_data = selectors.get_pipeline_kanban(organization=org, pipeline_id=pipeline.pk)
    all_pipelines = selectors.list_pipelines(organization=org)

    context = {
        "pipeline": pipeline,
        "all_pipelines": all_pipelines,
        "stages": kanban_data["stages"],
        "total_pipeline_value": kanban_data["total_pipeline_value"],
        "total_deals": kanban_data["total_deals"],
    }
    return render(request, "crm/pipeline_kanban.html", context)


@permission_required("crm.update")
def opportunity_stage_move_view(request: HttpRequest, public_id: str, stage_id: int) -> HttpResponse:
    """Move opportunity to a target stage via HTMX."""
    org = _get_org(request)
    opp = get_object_or_404(Opportunity.all_tenants, organization=org, public_id=public_id)
    target_stage = get_object_or_404(Stage.all_tenants, organization=org, pk=stage_id)

    services.move_opportunity_stage(
        organization=org,
        opportunity=opp,
        stage=target_stage,
        actor=request.user,
    )

    kanban_data = selectors.get_pipeline_kanban(organization=org, pipeline_id=opp.pipeline_id)
    context = {
        "pipeline": opp.pipeline,
        "stages": kanban_data["stages"],
        "total_pipeline_value": kanban_data["total_pipeline_value"],
        "total_deals": kanban_data["total_deals"],
    }
    return render(request, "crm/partials/kanban_board_inner.html", context)


@permission_required("crm.create")
def opportunity_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new sales opportunity deal."""
    org = _get_org(request)

    if request.method == "POST":
        form = OpportunityForm(request.POST, organization=org)
        if form.is_valid():
            tags_raw = form.cleaned_data.get("tags_csv", "")
            tag_names = [t.strip() for t in tags_raw.split(",") if t.strip()]

            opp = services.create_opportunity(
                organization=org,
                title=form.cleaned_data["title"],
                pipeline=form.cleaned_data["pipeline"],
                stage=form.cleaned_data["stage"],
                customer=form.cleaned_data["customer"],
                expected_value=form.cleaned_data["expected_value"],
                probability_percent=form.cleaned_data["probability_percent"],
                expected_close_date=form.cleaned_data["expected_close_date"],
                assigned_to=form.cleaned_data["assigned_to"],
                notes=form.cleaned_data["notes"],
                tag_names=tag_names,
                actor=request.user,
            )
            messages.success(request, _("Deal '%(title)s' created.") % {"title": opp.title})
            return redirect("crm:opportunity_detail", public_id=opp.public_id)
    else:
        form = OpportunityForm(organization=org)

    return render(request, "crm/opportunity_form.html", {"form": form, "title": _("New Deal")})


@permission_required("crm.view")
def opportunity_detail_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Overview of a single opportunity deal."""
    org = _get_org(request)
    opp = get_object_or_404(Opportunity.all_tenants, organization=org, public_id=public_id)

    interactions = selectors.list_interactions(organization=org, opportunity_id=opp.pk)
    tasks = selectors.list_tasks(organization=org, opportunity_id=opp.pk)

    stages = Stage.all_tenants.filter(organization=org, pipeline=opp.pipeline).order_by("order")

    return render(
        request,
        "crm/opportunity_detail.html",
        {
            "opp": opp,
            "stages": stages,
            "interactions": interactions,
            "tasks": tasks,
            "interaction_form": InteractionForm(),
            "task_form": CrmTaskForm(organization=org),
        },
    )


# =============================================================================
# 3. Customer 360 & Inactive Segments
# =============================================================================


@permission_required("crm.view")
def customer_360_index_view(request: HttpRequest) -> HttpResponse:
    """Directory index to select a customer for 360 overview."""
    org = _get_org(request)
    query = request.GET.get("search", "")
    customers = Customer.all_tenants.filter(organization=org, status="active")
    if query:
        customers = customers.filter(name__icontains=query)

    paginator = Paginator(customers.order_by("name"), 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "crm/customer_360_index.html",
        {"page_obj": page_obj, "customers": page_obj.object_list, "search": query},
    )


@permission_required("crm.view")
def customer_360_view(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Holistic Customer 360 profile view: deals, touchpoints, tasks, and sales."""
    org = _get_org(request)
    data = selectors.get_customer_360(organization=org, customer_id=customer_id)
    if not data:
        messages.error(request, _("Customer not found."))
        return redirect("crm:customer_360_index")

    context = {
        **data,
        "interaction_form": InteractionForm(),
        "task_form": CrmTaskForm(organization=org),
    }
    return render(request, "crm/customer_360.html", context)


@permission_required("crm.view")
def inactive_customers_view(request: HttpRequest) -> HttpResponse:
    """List of inactive customer accounts past activity thresholds."""
    org = _get_org(request)
    days_threshold = int(request.GET.get("days", "60"))

    inactive_list = selectors.get_inactive_customers(organization=org, days_threshold=days_threshold)

    return render(
        request,
        "crm/inactive_customers.html",
        {
            "inactive_customers": inactive_list,
            "days_threshold": days_threshold,
            "count": len(inactive_list),
        },
    )


# =============================================================================
# 4. Activities: Log Interaction & Tasks
# =============================================================================


@permission_required("crm.create")
def log_interaction_view(request: HttpRequest) -> HttpResponse:
    """HTMX endpoint to record an interaction."""
    org = _get_org(request)
    if request.method != "POST":
        return HttpResponse(status=405)

    form = InteractionForm(request.POST)
    if form.is_valid():
        lead_id = request.POST.get("lead_id")
        customer_id = request.POST.get("customer_id")
        opportunity_id = request.POST.get("opportunity_id")

        lead = Lead.all_tenants.filter(organization=org, pk=lead_id).first() if lead_id else None
        cust = Customer.all_tenants.filter(organization=org, pk=customer_id).first() if customer_id else None
        opp = (
            Opportunity.all_tenants.filter(organization=org, pk=opportunity_id).first()
            if opportunity_id
            else None
        )

        interaction = services.log_interaction(
            organization=org,
            summary=form.cleaned_data["summary"],
            type=form.cleaned_data["type"],
            details=form.cleaned_data["details"],
            lead=lead,
            customer=cust,
            opportunity=opp,
            actor=request.user,
        )
        return render(request, "crm/partials/interaction_item.html", {"item": interaction})

    return HttpResponse(status=400)


@permission_required("crm.view")
def task_list_view(request: HttpRequest) -> HttpResponse:
    """Task manager view."""
    org = _get_org(request)
    status_filter = request.GET.get("status", "")
    tasks = selectors.list_tasks(organization=org, status=status_filter or None)

    return render(
        request,
        "crm/task_list.html",
        {"tasks": tasks, "status_filter": status_filter, "form": CrmTaskForm(organization=org)},
    )


@permission_required("crm.update")
def task_toggle_complete_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """HTMX toggle to complete a task."""
    org = _get_org(request)
    task = get_object_or_404(CrmTask.all_tenants, organization=org, public_id=public_id)

    task = services.complete_crm_task(organization=org, task=task, actor=request.user)
    return render(request, "crm/partials/task_item.html", {"task": task})
