"""Tenancy workspace dashboard widgets: Onboarding checklist and Workspace overview KPI."""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.http import HttpRequest
from django.utils.translation import gettext as _

from apps.core.dashboard import DashboardWidget
from apps.core.metrics import get_metric_count
from apps.core.permissions import has_permission
from apps.tenancy.models import Branch, Membership, Warehouse


class OnboardingChecklistWidget(DashboardWidget):
    """Empty-state and onboarding checklist guide for newly provisioned workspaces."""

    widget_id = "onboarding_checklist"
    title = _("Getting Started with Business OS")
    description = _("Setup steps to get your organization fully operational")
    col_span = 12
    order = 1
    template_name = "tenancy/dashboard/onboarding_checklist.html"

    def _evaluate_steps(self, organization: Any) -> tuple[list[dict[str, Any]], bool]:
        # 1. Profile & regional setup
        profile_done = bool(organization.base_currency and organization.timezone)

        # 2. Branches & Locations
        branches_count = Branch.all_tenants.filter(organization=organization).count()
        branches_done = branches_count >= 1

        # 3. Team Collaboration
        members_count = Membership.all_tenants.filter(organization=organization, status="active").count()
        # Initial provisioning creates owner membership (1); done if > 1 member exists
        team_done = members_count > 1

        # 4. Integrations & API Keys
        api_key_model = apps.get_model("core", "ApiKey")
        api_keys_done = api_key_model.all_tenants.filter(organization=organization).exists()

        # 5. Billing & Plan
        sub_model = apps.get_model("billing", "Subscription")
        sub_done = sub_model.all_tenants.filter(organization=organization).exists()

        steps = [
            {
                "id": "profile",
                "title": _("Configure Business Profile"),
                "description": _("Set your workspace name, default currency, time zone, and fiscal year."),
                "is_completed": profile_done,
                "url": "/settings/",
                "icon": "building",
            },
            {
                "id": "branches",
                "title": _("Establish Branches & Locations"),
                "description": _("Define physical branch locations and warehouse inventory points."),
                "is_completed": branches_done,
                "url": "/settings/branches/",
                "icon": "map-pin",
            },
            {
                "id": "team",
                "title": _("Invite Your Team"),
                "description": _("Invite colleagues and assign roles with granular module permissions."),
                "is_completed": team_done,
                "url": "/settings/users/",
                "icon": "users",
            },
            {
                "id": "integrations",
                "title": _("Connect API Keys & Integrations"),
                "description": _("Generate secure API keys to integrate scripts, e-commerce, or webhooks."),
                "is_completed": api_keys_done,
                "url": "/settings/api-keys/",
                "icon": "key",
            },
            {
                "id": "subscription",
                "title": _("Explore Modules & Subscription"),
                "description": _(
                    "Manage plan entitlements, explore ERP bundles, and review billing invoices."
                ),
                "is_completed": sub_done,
                "url": "/billing/",
                "icon": "credit-card",
            },
        ]
        all_completed = all(s["is_completed"] for s in steps)
        return steps, all_completed

    def is_visible(self, request: HttpRequest, organization: Any) -> bool:
        # Check if user explicitly dismissed the checklist for this workspace
        dismissed = request.session.get(f"dismiss_checklist_{organization.pk}", False)
        manually_triggered = bool(
            request.GET.get("show_checklist") or request.session.get(f"show_checklist_{organization.pk}", False)
        )

        if dismissed and not manually_triggered:
            return False

        _, all_completed = self._evaluate_steps(organization)
        if all_completed and not manually_triggered:
            return False

        return True

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        steps, all_completed = self._evaluate_steps(organization)
        completed_count = sum(1 for s in steps if s["is_completed"])
        total_count = len(steps)
        percent_complete = int((completed_count / total_count) * 100) if total_count else 0

        return {
            "steps": steps,
            "completed_count": completed_count,
            "total_count": total_count,
            "percent_complete": percent_complete,
            "all_completed": all_completed,
            "can_manage_settings": has_permission(request.user, "settings.manage", organization=organization),
        }


class WorkspaceOverviewWidget(DashboardWidget):
    """4-card KPI metric summary of workspace capacity and operational health."""

    widget_id = "workspace_overview"
    title = _("Workspace Overview")
    description = _("Key metrics for current workspace capacity and resource utilization")
    col_span = 12
    order = 20
    template_name = "tenancy/dashboard/workspace_overview.html"

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        # 1. Active subscription
        sub_model = apps.get_model("billing", "Subscription")
        sub = sub_model.all_tenants.filter(organization=organization).select_related("plan").first()
        plan_name = sub.plan.name if (sub and sub.plan) else "Starter"
        plan_status = sub.status if sub else "active"

        # 2. Team members count
        members_count = Membership.all_tenants.filter(organization=organization, status="active").count()

        # 3. Branches and warehouses
        branch_count = Branch.all_tenants.filter(organization=organization).count()
        warehouse_count = Warehouse.all_tenants.filter(organization=organization).count()

        # 4. Monthly metered API calls
        monthly_api_calls = get_metric_count(organization.pk, "api_calls")

        return {
            "plan_name": plan_name,
            "plan_status": plan_status,
            "members_count": members_count,
            "branch_count": branch_count,
            "warehouse_count": warehouse_count,
            "monthly_api_calls": monthly_api_calls,
        }
