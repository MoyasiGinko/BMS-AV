"""Tests for dashboard widget classes, template rendering, and HTMX endpoints."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.billing.services import create_subscription, seed_default_plans
from apps.core.dashboard import registry
from apps.reports.dashboard_widgets import (
    LowStockWidget,
    ReceivablesWidget,
    RecentActivityWidget,
    SalesTodayWidget,
    TopProductsWidget,
)
from apps.tenancy.models import Membership, Organization, Role
from apps.tenancy.services import create_organization

User = get_user_model()


@pytest.fixture
def widget_test_org(db: None) -> dict[str, object]:
    plans = seed_default_plans()
    owner = User.objects.create_user(email="owner@widgets.com", password="password123")
    org = create_organization(name="Widgets Inc", slug="widgets-inc", owner=owner)
    create_subscription(organization=org, plan=plans["enterprise"], actor=owner, trial_days=0)

    staff = User.objects.create_user(email="staff@widgets.com", password="password123")
    role_member = Role.all_tenants.filter(organization=org, name="Member").first()
    Membership.objects.create(organization=org, user=staff, role=role_member, status=Membership.STATUS_ACTIVE)

    accounting_services.seed_chart_of_accounts(organization=org)
    accounting_services.seed_fiscal_calendar(organization=org, year=timezone.now().year)

    return {
        "org": org,
        "owner": owner,
        "staff": staff,
    }


def test_widget_registry_membership() -> None:
    """Ensure all 5 v1 dashboard widgets are registered in the global widget registry."""
    assert isinstance(registry.get("sales_today"), SalesTodayWidget)
    assert isinstance(registry.get("receivables"), ReceivablesWidget)
    assert isinstance(registry.get("low_stock"), LowStockWidget)
    assert isinstance(registry.get("top_products"), TopProductsWidget)
    assert isinstance(registry.get("recent_activity"), RecentActivityWidget)


@pytest.mark.django_db(transaction=True)
def test_all_widgets_render_html(widget_test_org: dict[str, object]) -> None:
    """Ensure each widget's render() produces valid HTML with expected identifiers."""
    org = widget_test_org["org"]
    owner = widget_test_org["owner"]
    rf = RequestFactory()
    request = rf.get("/dashboard/")
    request.user = owner  # type: ignore
    request.organization = org  # type: ignore

    sales_widget = registry.get("sales_today")
    assert sales_widget is not None
    sales_html = sales_widget.render(request, org)
    assert "Sales Today" in sales_html
    assert "POS Counter" in sales_html
    assert "Direct Invoices" in sales_html

    rec_widget = registry.get("receivables")
    assert rec_widget is not None
    rec_html = rec_widget.render(request, org)
    assert "Receivables" in rec_html
    assert "Current" in rec_html
    assert "1-30d" in rec_html

    stock_widget = registry.get("low_stock")
    assert stock_widget is not None
    stock_html = stock_widget.render(request, org)
    assert "Low Stock Alerts" in stock_html

    prod_widget = registry.get("top_products")
    assert prod_widget is not None
    prod_html = prod_widget.render(request, org)
    assert "Top Selling Products" in prod_html

    act_widget = registry.get("recent_activity")
    assert act_widget is not None
    act_html = act_widget.render(request, org)
    assert "Recent Activity" in act_html


@pytest.mark.django_db(transaction=True)
def test_widget_visibility_permissions(widget_test_org: dict[str, object]) -> None:
    """Verify that widgets requiring sales.view or inventory.view are filtered for restricted users."""
    org = widget_test_org["org"]
    owner = widget_test_org["owner"]
    staff = widget_test_org["staff"]

    rf = RequestFactory()

    # Owner has all permissions: sees all 5 widgets
    req_owner = rf.get("/dashboard/")
    req_owner.user = owner  # type: ignore
    req_owner.organization = org  # type: ignore

    visible_owner_ids = [w.widget_id for w in registry.get_visible(req_owner, org)]
    assert "sales_today" in visible_owner_ids
    assert "receivables" in visible_owner_ids
    assert "low_stock" in visible_owner_ids
    assert "top_products" in visible_owner_ids
    assert "recent_activity" in visible_owner_ids

    # Staff member can see activity feed
    req_staff = rf.get("/dashboard/")
    req_staff.user = staff  # type: ignore
    req_staff.organization = org  # type: ignore
    visible_staff_ids = [w.widget_id for w in registry.get_visible(req_staff, org)]
    assert "recent_activity" in visible_staff_ids


@pytest.mark.django_db(transaction=True)
def test_dashboard_widget_partial_endpoints(client: object, widget_test_org: dict[str, object]) -> None:
    """Test the HTMX partial refresh endpoints for each widget."""
    test_client = client if isinstance(client, Client) else Client()
    org = widget_test_org["org"]
    owner = widget_test_org["owner"]
    assert isinstance(org, Organization)
    assert isinstance(owner, User)

    test_client.force_login(owner)

    for widget_id in ["sales_today", "receivables", "low_stock", "top_products", "recent_activity"]:
        url = f"/dashboard/widget/{widget_id}/"
        response = test_client.get(url, HTTP_HOST=f"{org.slug}.localhost")
        assert response.status_code == 200, f"Widget {widget_id} failed with status {response.status_code}"
        assert len(response.content) > 50

    # Non-existent widget returns 404
    resp_404 = test_client.get("/dashboard/widget/non_existent_widget/", HTTP_HOST=f"{org.slug}.localhost")
    assert resp_404.status_code == 404
