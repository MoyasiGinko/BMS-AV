"""Tests for dashboard widget classes, template rendering, and HTMX endpoints."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.accounting import services as accounting_services
from apps.billing.services import create_subscription, seed_default_plans
from apps.core.dashboard import registry
from apps.reports.dashboard_widgets import (
    BranchPerformanceWidget,
    CashPositionWidget,
    ExpenseTrendWidget,
    LowStockWidget,
    PayablesWidget,
    ProfitTrendWidget,
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
    """Ensure all 10 dashboard widgets are registered in the global widget registry."""
    assert isinstance(registry.get("sales_today"), SalesTodayWidget)
    assert isinstance(registry.get("receivables"), ReceivablesWidget)
    assert isinstance(registry.get("low_stock"), LowStockWidget)
    assert isinstance(registry.get("top_products"), TopProductsWidget)
    assert isinstance(registry.get("recent_activity"), RecentActivityWidget)
    assert isinstance(registry.get("payables"), PayablesWidget)
    assert isinstance(registry.get("expense_trend"), ExpenseTrendWidget)
    assert isinstance(registry.get("cash_position"), CashPositionWidget)
    assert isinstance(registry.get("profit_trend"), ProfitTrendWidget)
    assert isinstance(registry.get("branch_performance"), BranchPerformanceWidget)


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

    pay_widget = registry.get("payables")
    assert pay_widget is not None
    pay_html = pay_widget.render(request, org)
    assert "Accounts Payable" in pay_html

    exp_widget = registry.get("expense_trend")
    assert exp_widget is not None
    exp_html = exp_widget.render(request, org)
    assert "Expense Trend" in exp_html

    cash_widget = registry.get("cash_position")
    assert cash_widget is not None
    cash_html = cash_widget.render(request, org)
    assert "Cash Position" in cash_html

    profit_widget = registry.get("profit_trend")
    assert profit_widget is not None
    profit_html = profit_widget.render(request, org)
    assert "Profitability Trend" in profit_html

    branch_widget = registry.get("branch_performance")
    assert branch_widget is not None
    branch_html = branch_widget.render(request, org)
    assert "Branch Performance" in branch_html


@pytest.mark.django_db(transaction=True)
def test_widget_visibility_permissions(widget_test_org: dict[str, object]) -> None:
    """Verify that widgets requiring specific role permissions are appropriately filtered."""
    org = widget_test_org["org"]
    owner = widget_test_org["owner"]
    staff = widget_test_org["staff"]

    rf = RequestFactory()

    # Owner has all permissions: sees all 10 widgets
    req_owner = rf.get("/dashboard/")
    req_owner.user = owner  # type: ignore
    req_owner.organization = org  # type: ignore

    visible_owner_ids = [w.widget_id for w in registry.get_visible(req_owner, org)]
    assert "sales_today" in visible_owner_ids
    assert "receivables" in visible_owner_ids
    assert "low_stock" in visible_owner_ids
    assert "top_products" in visible_owner_ids
    assert "recent_activity" in visible_owner_ids
    assert "payables" in visible_owner_ids
    assert "expense_trend" in visible_owner_ids
    assert "cash_position" in visible_owner_ids
    assert "profit_trend" in visible_owner_ids
    assert "branch_performance" in visible_owner_ids

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

    widgets_to_test = [
        "sales_today",
        "receivables",
        "low_stock",
        "top_products",
        "recent_activity",
        "payables",
        "expense_trend",
        "cash_position",
        "profit_trend",
        "branch_performance",
    ]

    for widget_id in widgets_to_test:
        url = f"/dashboard/widget/{widget_id}/"
        response = test_client.get(url, HTTP_HOST=f"{org.slug}.localhost")
        assert response.status_code == 200, f"Widget {widget_id} failed with status {response.status_code}"
        assert len(response.content) > 50

    # Non-existent widget returns 404
    resp_404 = test_client.get("/dashboard/widget/non_existent_widget/", HTTP_HOST=f"{org.slug}.localhost")
    assert resp_404.status_code == 404
