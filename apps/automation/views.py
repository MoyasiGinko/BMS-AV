"""Web views and HTMX endpoints for the automation engine."""

from __future__ import annotations

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.automation.actions import action_registry
from apps.automation.forms import AutomationRuleForm, AutomationTestForm
from apps.automation.selectors import (
    get_automation_overview_metrics,
    get_automation_rule_by_id,
    get_automation_run_by_id,
    list_automation_rules,
    list_automation_runs,
)
from apps.automation.services import (
    create_automation_rule,
    delete_automation_rule,
    execute_rule,
    instantiate_rule_from_template,
    test_rule_simulation,
    toggle_automation_rule,
    update_automation_rule,
)
from apps.automation.templates_catalog import list_templates
from apps.core.permissions import permission_required
from apps.core.tenant_context import get_current_organization_id


@login_required
@permission_required("automation.view")
def rule_list_view(request: HttpRequest) -> HttpResponse:
    """Dashboard overview and list of automation rules."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    search = request.GET.get("search", "").strip()
    trigger_type = request.GET.get("trigger_type", "").strip()
    is_active_param = request.GET.get("is_active", "").strip()

    is_active = None
    if is_active_param == "true":
        is_active = True
    elif is_active_param == "false":
        is_active = False

    rules = list_automation_rules(
        organization_id=org_id,
        is_active=is_active,
        trigger_type=trigger_type or None,
        search=search or None,
    )

    metrics = get_automation_overview_metrics(organization_id=org_id)

    context = {
        "rules": rules,
        "metrics": metrics,
        "search": search,
        "trigger_type": trigger_type,
        "is_active_param": is_active_param,
    }

    if request.headers.get("HX-Request") and request.GET.get("partial") == "table":
        return render(request, "automation/partials/rules_table.html", context)

    return render(request, "automation/rule_list.html", context)


@login_required
@permission_required("automation.manage")
def template_list_view(request: HttpRequest) -> HttpResponse:
    """Catalog of pre-configured automation templates."""
    templates = list_templates()
    return render(request, "automation/template_list.html", {"templates": templates})


@login_required
@permission_required("automation.manage")
@require_POST
def template_instantiate_view(request: HttpRequest, template_key: str) -> HttpResponse:
    """One-click instantiation of an automation rule from a catalog template."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    try:
        rule = instantiate_rule_from_template(
            organization=org_id,
            template_key=template_key,
            actor=request.user,
        )
        messages.success(request, _(f"Rule '{rule.name}' created successfully from template."))
        return redirect("automation:rule_edit", rule_id=rule.public_id)
    except ValidationError as err:
        messages.error(request, str(err.message if hasattr(err, "message") else err))
        return redirect("automation:template_list")


@login_required
@permission_required("automation.manage")
def rule_create_view(request: HttpRequest) -> HttpResponse:
    """Visual builder screen for creating a new automation rule."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    if request.method == "POST":
        form = AutomationRuleForm(request.POST)
        if form.is_valid():
            try:
                rule = create_automation_rule(
                    organization=org_id,
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data["description"],
                    trigger_type=form.cleaned_data["trigger_type"],
                    trigger_event=form.cleaned_data["trigger_event"],
                    conditions=form.cleaned_data["conditions_json"],
                    actions=form.cleaned_data["actions_json"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                messages.success(request, _(f"Rule '{rule.name}' created successfully."))
                return redirect("automation:rule_list")
            except ValidationError as err:
                form.add_error(None, str(err.message if hasattr(err, "message") else err))
    else:
        initial_data = {
            "conditions_json": json.dumps(
                [{"field": "quantity_on_hand", "operator": "less_than_or_equal", "value": 10}],
                indent=2,
            ),
            "actions_json": json.dumps(
                [{"action_type": "create_draft_po", "params": {"quantity": 25}}],
                indent=2,
            ),
        }
        form = AutomationRuleForm(initial=initial_data)

    available_actions = action_registry.get_available_actions()
    return render(
        request,
        "automation/rule_builder.html",
        {"form": form, "is_new": True, "available_actions": available_actions},
    )


@login_required
@permission_required("automation.manage")
def rule_edit_view(request: HttpRequest, rule_id: str) -> HttpResponse:
    """Edit an existing automation rule."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    rule = get_automation_rule_by_id(organization_id=org_id, rule_id=rule_id)
    if not rule:
        messages.error(request, _("Automation rule not found."))
        return redirect("automation:rule_list")

    if request.method == "POST":
        form = AutomationRuleForm(request.POST)
        if form.is_valid():
            try:
                update_automation_rule(
                    rule=rule,
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data["description"],
                    trigger_type=form.cleaned_data["trigger_type"],
                    trigger_event=form.cleaned_data["trigger_event"],
                    conditions=form.cleaned_data["conditions_json"],
                    actions=form.cleaned_data["actions_json"],
                    is_active=form.cleaned_data["is_active"],
                    actor=request.user,
                )
                messages.success(request, _("Rule updated successfully."))
                return redirect("automation:rule_list")
            except ValidationError as err:
                form.add_error(None, str(err.message if hasattr(err, "message") else err))
    else:
        initial_data = {
            "name": rule.name,
            "description": rule.description,
            "trigger_type": rule.trigger_type,
            "trigger_event": rule.trigger_event,
            "is_active": rule.is_active,
            "conditions_json": json.dumps(rule.conditions, indent=2),
            "actions_json": json.dumps(rule.actions, indent=2),
        }
        form = AutomationRuleForm(initial=initial_data)

    available_actions = action_registry.get_available_actions()
    return render(
        request,
        "automation/rule_builder.html",
        {
            "form": form,
            "rule": rule,
            "is_new": False,
            "available_actions": available_actions,
        },
    )


@login_required
@permission_required("automation.manage")
@require_POST
def rule_toggle_view(request: HttpRequest, rule_id: str) -> HttpResponse:
    """HTMX endpoint to toggle a rule's active state."""
    org_id = get_current_organization_id()
    if not org_id:
        return HttpResponse(status=401)

    rule = get_automation_rule_by_id(organization_id=org_id, rule_id=rule_id)
    if not rule:
        return HttpResponse(status=404)

    try:
        toggle_automation_rule(rule=rule, actor=request.user)
    except ValidationError as err:
        messages.error(request, str(err.message if hasattr(err, "message") else err))

    if request.headers.get("HX-Request"):
        return render(request, "automation/partials/rule_row.html", {"rule": rule})

    return redirect("automation:rule_list")


@login_required
@permission_required("automation.manage")
@require_POST
def rule_delete_view(request: HttpRequest, rule_id: str) -> HttpResponse:
    """Delete an automation rule."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    rule = get_automation_rule_by_id(organization_id=org_id, rule_id=rule_id)
    if rule:
        delete_automation_rule(rule=rule, actor=request.user)
        messages.success(request, _(f"Rule '{rule.name}' deleted successfully."))

    return redirect("automation:rule_list")


@login_required
@permission_required("automation.run")
def rule_test_view(request: HttpRequest, rule_id: str) -> HttpResponse:
    """Simulation test bench for evaluating rule conditions against mock data."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    rule = get_automation_rule_by_id(organization_id=org_id, rule_id=rule_id)
    if not rule:
        messages.error(request, _("Automation rule not found."))
        return redirect("automation:rule_list")

    simulation_result = None

    if request.method == "POST":
        form = AutomationTestForm(request.POST)
        if form.is_valid():
            payload = form.cleaned_data["payload_json"]
            execute_live = request.POST.get("execute_live") == "true"
            if execute_live:
                try:
                    run = execute_rule(
                        rule=rule,
                        trigger_event_type=rule.trigger_event or "test.event",
                        trigger_payload=payload,
                        actor=request.user,
                    )
                    messages.success(request, _(f"Live run executed: {run.status.upper()}"))
                    return redirect("automation:run_detail", run_id=run.public_id)
                except Exception as err:
                    messages.error(request, f"Execution error: {err}")
            else:
                simulation_result = test_rule_simulation(
                    rule=rule,
                    sample_payload=payload,
                )
    else:
        initial_payload = {
            "sku": "PROD-SAMPLE",
            "quantity_on_hand": 5,
            "customer_name": "Test Customer",
            "amount": 12500,
        }
        form = AutomationTestForm(initial={"payload_json": json.dumps(initial_payload, indent=2)})

    return render(
        request,
        "automation/rule_test.html",
        {
            "rule": rule,
            "form": form,
            "simulation_result": simulation_result,
        },
    )


@login_required
@permission_required("automation.view")
def run_list_view(request: HttpRequest) -> HttpResponse:
    """Audit log of past automation rule executions."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    status = request.GET.get("status", "").strip()
    rule_id = request.GET.get("rule_id", "").strip()

    runs = list_automation_runs(
        organization_id=org_id,
        rule_id=rule_id or None,
        status=status or None,
        limit=100,
    )
    rules = list_automation_rules(organization_id=org_id)

    return render(
        request,
        "automation/run_list.html",
        {
            "runs": runs,
            "rules": rules,
            "selected_status": status,
            "selected_rule_id": rule_id,
        },
    )


@login_required
@permission_required("automation.view")
def run_detail_view(request: HttpRequest, run_id: str) -> HttpResponse:
    """Detailed inspection of a specific execution run."""
    org_id = get_current_organization_id()
    if not org_id:
        return redirect("accounts:login")

    run = get_automation_run_by_id(organization_id=org_id, run_id=run_id)
    if not run:
        messages.error(request, _("Automation run not found."))
        return redirect("automation:run_list")

    return render(request, "automation/run_detail.html", {"run": run})
