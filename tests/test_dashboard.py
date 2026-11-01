"""Comprehensive tests for Dashboard shell, widget registry, and onboarding checklist.

Covers:
- Widget registry: registration, unregistration, retrieval, and sorting.
- Three-layer filtering: plan module entitlement, user role permission, custom is_visible hook.
- Core starter widgets: QuickActionsWidget, RecentAuditActivityWidget.
- Tenancy onboarding checklist: dynamic milestone evaluation, percent complete, dismiss & reset.
- Workspace overview KPI widget: plan tier, member count, branch/warehouse count, metered usage.
- Dashboard view routing: unauthenticated redirect, full page render, HTMX partial widget swap.
- Cross-tenant isolation.
"""

from __future__ import annotations

from typing import Any

import pytest
from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpRequest
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.billing.models import Plan
from apps.billing.services import create_subscription, seed_default_plans
from apps.core.dashboard import (
    DashboardWidget,
    WidgetRegistry,
)
from apps.core.models import AuditLog
from apps.core.permissions import clear_feature_overrides, set_feature_override
from apps.tenancy.dashboard_widgets import (
    OnboardingChecklistWidget,
    WorkspaceOverviewWidget,
)
from apps.tenancy.models import Membership, Organization, Role
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_state() -> Any:
    cache.clear()
    clear_feature_overrides()
    yield
    cache.clear()
    clear_feature_overrides()


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def owner_a(db: None) -> User:
    return User.objects.create_user(email="dash_owner_a@example.com", password="Password123!")


@pytest.fixture
def viewer_a(db: None) -> User:
    return User.objects.create_user(email="dash_viewer_a@example.com", password="Password123!")


@pytest.fixture
def owner_b(db: None) -> User:
    return User.objects.create_user(email="dash_owner_b@example.com", password="Password123!")


@pytest.fixture
def org_a(db: None, owner_a: User, viewer_a: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Apex Systems", slug="apex", owner=owner_a)
    create_subscription(organization=org, plan=plans["starter"], actor=owner_a, trial_days=0)
    role_viewer = Role.all_tenants.filter(organization=org, name="Viewer").first()
    assert role_viewer is not None
    Membership.all_tenants.create(
        organization=org,
        user=viewer_a,
        role=role_viewer,
        status=Membership.STATUS_ACTIVE,
    )
    return org


@pytest.fixture
def org_b(db: None, owner_b: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Nexus Logistics", slug="nexus", owner=owner_b)
    create_subscription(organization=org, plan=plans["growth"], actor=owner_b, trial_days=0)
    return org


class SampleCustomWidget(DashboardWidget):
    widget_id = "sample_custom"
    title = "Custom Widget"
    template_name = "core/dashboard/widgets/quick_actions.html"
    order = 50

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {"custom_key": "custom_val"}


class EntitledModuleWidget(DashboardWidget):
    widget_id = "entitled_module_widget"
    title = "Inventory Insights"
    module = "inventory"
    template_name = "core/dashboard/widgets/quick_actions.html"
    order = 60

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {}


class RestrictedPermissionWidget(DashboardWidget):
    widget_id = "restricted_perm_widget"
    title = "Settings Control"
    permission = "settings.manage"
    template_name = "core/dashboard/widgets/quick_actions.html"
    order = 70

    def get_context(self, request: HttpRequest, organization: Any) -> dict[str, Any]:
        return {}


@pytest.mark.django_db
class TestWidgetRegistry:
    def test_register_and_retrieve_widget(self) -> None:
        reg = WidgetRegistry()
        widget = SampleCustomWidget()
        reg.register(widget)

        assert reg.get("sample_custom") == widget
        assert len(reg.list_all()) == 1

        reg.unregister("sample_custom")
        assert reg.get("sample_custom") is None

    def test_module_entitlement_filtering(self, org_a: Organization, owner_a: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner_a

        reg = WidgetRegistry()
        widget = EntitledModuleWidget()
        reg.register(widget)

        # Starter plan doesn't have inventory module by default -> should be hidden
        visible = reg.get_visible(request, org_a)
        assert widget not in visible

        # Override entitlement -> should become visible
        set_feature_override(org_a.id, "inventory", True)
        visible_override = reg.get_visible(request, org_a)
        assert widget in visible_override

    def test_role_permission_filtering(self, org_a: Organization, owner_a: User, viewer_a: User) -> None:
        factory = RequestFactory()
        reg = WidgetRegistry()
        widget = RestrictedPermissionWidget()
        reg.register(widget)

        # Owner has settings.manage -> visible
        req_owner = factory.get("/")
        req_owner.user = owner_a
        assert widget in reg.get_visible(req_owner, org_a)

        # Viewer role does not have settings.manage -> hidden
        req_viewer = factory.get("/")
        req_viewer.user = viewer_a
        assert widget not in reg.get_visible(req_viewer, org_a)


@pytest.mark.django_db
class TestOnboardingChecklistWidget:
    def test_checklist_steps_and_progress(self, org_a: Organization, owner_a: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner_a
        request.session = {}

        checklist_widget = OnboardingChecklistWidget()
        context = checklist_widget.get_context(request, org_a)

        assert "steps" in context
        assert len(context["steps"]) == 5
        assert context["total_count"] == 5
        # Org provisioned with currency and 1 branch and subscription
        assert context["completed_count"] >= 2
        assert 0 <= context["percent_complete"] <= 100

    def test_checklist_dismissal_and_reset(self, org_a: Organization, owner_a: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner_a
        request.session = {}

        checklist_widget = OnboardingChecklistWidget()
        assert checklist_widget.is_visible(request, org_a) is True

        # Dismiss checklist for org_a
        request.session[f"dismiss_checklist_{org_a.pk}"] = True
        assert checklist_widget.is_visible(request, org_a) is False

        # Reset dismissal
        del request.session[f"dismiss_checklist_{org_a.pk}"]
        assert checklist_widget.is_visible(request, org_a) is True

    def test_checklist_hidden_when_all_completed_until_manually_triggered(
        self, org_a: Organization, owner_a: User
    ) -> None:
        checklist_widget = OnboardingChecklistWidget()
        factory = RequestFactory()

        with patch.object(
            OnboardingChecklistWidget,
            "_evaluate_steps",
            return_value=([{"id": "s", "is_completed": True}], True),
        ):
            # 1. By default, when all steps are completed, it is not visible
            request = factory.get("/")
            request.user = owner_a
            request.session = {}
            assert checklist_widget.is_visible(request, org_a) is False

            # 2. When manually triggered via query parameter ?show_checklist=1
            req_query = factory.get("/?show_checklist=1")
            req_query.user = owner_a
            req_query.session = {}
            assert checklist_widget.is_visible(req_query, org_a) is True

            # 3. When manually triggered via session flag (e.g. clicked "Show Checklist")
            req_session = factory.get("/")
            req_session.user = owner_a
            req_session.session = {f"show_checklist_{org_a.pk}": True}
            assert checklist_widget.is_visible(req_session, org_a) is True

            # 4. If dismissed even with all complete, it remains False
            req_dismiss = factory.get("/")
            req_dismiss.user = owner_a
            req_dismiss.session = {f"dismiss_checklist_{org_a.pk}": True}
            assert checklist_widget.is_visible(req_dismiss, org_a) is False


@pytest.mark.django_db
class TestWorkspaceOverviewWidget:
    def test_overview_metrics(self, org_a: Organization, owner_a: User) -> None:
        factory = RequestFactory()
        request = factory.get("/")
        request.user = owner_a

        overview_widget = WorkspaceOverviewWidget()
        context = overview_widget.get_context(request, org_a)

        assert context["plan_name"] == "Starter"
        assert context["plan_status"] == "active"
        assert context["members_count"] == 2  # owner + viewer
        assert context["branch_count"] >= 1


@pytest.mark.django_db
class TestDashboardViews:
    def test_unauthenticated_redirect_to_login(self) -> None:
        client = Client()
        resp = client.get("/", HTTP_HOST="apex.localhost")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    def test_dashboard_full_page_render(self, org_a: Organization, owner_a: User) -> None:
        client = Client()
        client.force_login(owner_a)
        session = client.session
        session["active_org_id"] = org_a.id
        session.save()

        resp = client.get("/", HTTP_HOST="apex.localhost")
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Welcome to Apex Systems" in html
        assert "Getting Started with Business OS" in html
        assert "Workspace Overview" in html
        assert "Quick Actions" in html

    def test_htmx_partial_widgets_swap(self, org_a: Organization, owner_a: User) -> None:
        client = Client()
        client.force_login(owner_a)
        session = client.session
        session["active_org_id"] = org_a.id
        session.save()

        resp = client.get(
            "/?partial=widgets",
            HTTP_HOST="apex.localhost",
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        html = resp.content.decode()
        # Should render widgets without full <html> skeleton
        assert "<html" not in html
        assert "widget-onboarding_checklist" in html
        assert "widget-workspace_overview" in html

    def test_single_widget_partial_endpoint(self, org_a: Organization, owner_a: User) -> None:
        client = Client()
        client.force_login(owner_a)
        session = client.session
        session["active_org_id"] = org_a.id
        session.save()

        resp = client.get(
            "/dashboard/widget/workspace_overview/",
            HTTP_HOST="apex.localhost",
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert "Starter" in resp.content.decode()

    def test_dismiss_and_reset_checklist_endpoints(self, org_a: Organization, owner_a: User) -> None:
        client = Client()
        client.force_login(owner_a)
        session = client.session
        session["active_org_id"] = org_a.id
        session.save()

        # 1. Dismiss checklist via HTMX
        resp_dismiss = client.post(
            "/dashboard/checklist/dismiss/",
            HTTP_HOST="apex.localhost",
            HTTP_HX_REQUEST="true",
        )
        assert resp_dismiss.status_code == 200
        assert resp_dismiss.content == b""
        assert client.session.get(f"dismiss_checklist_{org_a.pk}") is True

        # 2. Next dashboard request will not contain onboarding checklist
        resp_after = client.get("/", HTTP_HOST="apex.localhost")
        assert resp_after.status_code == 200
        assert "widget-onboarding_checklist" not in resp_after.content.decode()
        assert "Show Checklist" in resp_after.content.decode()

        # 3. Reset checklist brings it back
        resp_reset = client.get("/dashboard/checklist/reset/", HTTP_HOST="apex.localhost", follow=True)
        assert resp_reset.status_code == 200
        assert "widget-onboarding_checklist" in resp_reset.content.decode()

    def test_cross_tenant_isolation(
        self,
        org_a: Organization,
        org_b: Organization,
        owner_a: User,
        owner_b: User,
    ) -> None:
        # Create an audit entry in Org A
        AuditLog.all_tenants.create(
            organization=org_a,
            actor=owner_a,
            action="tenant.provisioned",
            object_repr="Apex Systems Provisioned",
        )

        client_b = Client()
        client_b.force_login(owner_b)
        session_b = client_b.session
        session_b["active_org_id"] = org_b.id
        session_b.save()

        resp_b = client_b.get("/", HTTP_HOST="nexus.localhost")
        assert resp_b.status_code == 200
        html_b = resp_b.content.decode()
        assert "Welcome to Nexus Logistics" in html_b
        assert "Apex Systems Provisioned" not in html_b
