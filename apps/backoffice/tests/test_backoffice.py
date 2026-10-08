"""Comprehensive tests for Back-Office internal staff control plane.

Covers:
1. Staff permission enforcement (403 for non-staff, redirect for unauthenticated).
2. Overview dashboard & KPIs.
3. Tenant lookup, directory search, and 360-degree context.
4. Staff impersonation flow: session setup, audit logging, persistent banner rendering, and exit.
5. Subscription overrides: plan tier, status, dates, and mandatory reason validation.
6. Organization lifecycle status changes with audit trail.
7. Outbox events & background jobs inspection and retry mechanics.
8. Processed webhook inspection.
"""

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.billing.models import ProcessedWebhookEvent, Subscription
from apps.billing.services import provision_billing_subscription, seed_default_plans
from apps.core.hooks import register_provisioning_hook
from apps.core.models import AuditLog, OutboxEvent
from apps.tenancy.models import Organization
from apps.tenancy.services import provision_organization


@pytest.fixture
def seeded_plans() -> None:
    register_provisioning_hook(provision_billing_subscription)
    seed_default_plans()


@pytest.fixture
def org_one(seeded_plans: None) -> Organization:
    owner = User.objects.create_user(
        email="alpha_owner@example.com",
        password="Password123!",
        name="Alpha Owner",
    )
    return provision_organization(
        name="Acme Alpha",
        slug="acme-alpha",
        owner=owner,
        plan="starter",
    )


@pytest.fixture
def org_two(seeded_plans: None) -> Organization:
    owner = User.objects.create_user(
        email="beta_owner@example.com",
        password="Password123!",
        name="Beta Owner",
    )
    return provision_organization(
        name="Beta Global",
        slug="beta-global",
        owner=owner,
        plan="growth",
    )


@pytest.fixture
def staff_user() -> User:
    return User.objects.create_user(
        email="operator@bos.internal",
        password="Password123!",
        name="Operator Staff",
        is_staff=True,
    )


@pytest.fixture
def regular_user() -> User:
    return User.objects.create_user(
        email="regular@example.com",
        password="Password123!",
        name="Regular User",
        is_staff=False,
    )


@pytest.mark.django_db
class TestBackofficeAccessControl:
    """Validate strict internal staff access control across all back-office entry points."""

    def test_unauthenticated_redirect_to_login(self) -> None:
        client = Client()
        endpoints = [
            "/backoffice/",
            "/backoffice/tenants/",
            "/backoffice/jobs/",
            "/backoffice/webhooks/",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 302
            assert "/accounts/login/" in resp.url

    def test_non_staff_user_receives_403_forbidden(self, regular_user: User) -> None:
        client = Client()
        client.force_login(regular_user)

        endpoints = [
            "/backoffice/",
            "/backoffice/tenants/",
            "/backoffice/jobs/",
            "/backoffice/webhooks/",
        ]
        for ep in endpoints:
            resp = client.get(ep)
            assert resp.status_code == 403

    def test_staff_user_granted_access(self, staff_user: User) -> None:
        client = Client()
        client.force_login(staff_user)

        resp = client.get("/backoffice/")
        assert resp.status_code == 200
        assert "Operations Control Plane" in resp.content.decode()


@pytest.mark.django_db
class TestBackofficeTenantOperations:
    """Validate tenant lookup, filtering, detail, and lifecycle management."""

    def test_tenant_directory_search_and_filters(
        self, staff_user: User, org_one: Organization, org_two: Organization
    ) -> None:
        client = Client()
        client.force_login(staff_user)

        # 1. Full list contains both organizations
        resp = client.get("/backoffice/tenants/")
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Acme Alpha" in html
        assert "Beta Global" in html

        # 2. Search query filter
        resp_q = client.get("/backoffice/tenants/?q=Acme")
        html_q = resp_q.content.decode()
        assert "Acme Alpha" in html_q
        assert "Beta Global" not in html_q

        # 3. Plan filter
        resp_plan = client.get("/backoffice/tenants/?plan=growth")
        html_plan = resp_plan.content.decode()
        assert "Beta Global" in html_plan
        assert "Acme Alpha" not in html_plan

    def test_tenant_detail_view(self, staff_user: User, org_one: Organization) -> None:
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/backoffice/tenants/{org_one.public_id}/")
        assert resp.status_code == 200
        html = resp.content.decode()
        assert org_one.name in html
        assert org_one.slug in html
        assert "alpha_owner@example.com" in html
        assert "Starter" in html

    def test_tenant_status_update_with_audit(self, staff_user: User, org_one: Organization) -> None:
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/backoffice/tenants/{org_one.public_id}/update-status/",
            {
                "status": "suspended",
                "reason": "Payment overdue and violation of TOS",
            },
        )
        assert resp.status_code == 302

        org_one.refresh_from_db()
        assert org_one.status == "suspended"

        # Check AuditLog
        audit = AuditLog.all_tenants.filter(
            organization=org_one, action="backoffice.tenant_status_update"
        ).first()
        assert audit is not None
        assert audit.actor == staff_user
        assert audit.changes["new_status"] == "suspended"
        assert audit.changes["reason"] == "Payment overdue and violation of TOS"


@pytest.mark.django_db
class TestBackofficeSubscriptionOverrides:
    """Validate staff subscription overrides with audit trail and validation."""

    def test_override_subscription_tier_and_status(self, staff_user: User, org_one: Organization) -> None:
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/backoffice/tenants/{org_one.public_id}/override-subscription/",
            {
                "plan_slug": "enterprise",
                "status": "active",
                "reason": "Courtesy contract tier override approved by leadership",
            },
        )
        assert resp.status_code == 302

        sub = Subscription.all_tenants.filter(organization=org_one).first()
        assert sub is not None
        assert sub.plan.slug == "enterprise"
        assert sub.status == "active"

        # Check AuditLog
        audit = AuditLog.all_tenants.filter(
            organization=org_one, action="backoffice.subscription_override"
        ).first()
        assert audit is not None
        assert audit.actor == staff_user
        assert audit.changes["new_plan"] == "Enterprise"
        assert "Courtesy contract tier override" in audit.changes["reason"]

    def test_override_requires_mandatory_reason(self, staff_user: User, org_one: Organization) -> None:
        client = Client()
        client.force_login(staff_user)

        resp = client.post(
            f"/backoffice/tenants/{org_one.public_id}/override-subscription/",
            {
                "plan_slug": "business",
                "status": "active",
                "reason": "",  # Missing reason
            },
        )
        assert resp.status_code == 302

        # Sub should NOT have changed to business
        sub = Subscription.all_tenants.filter(organization=org_one).first()
        assert sub is not None
        assert sub.plan.slug == "starter"


@pytest.mark.django_db
class TestBackofficeImpersonation:
    """Validate staff impersonation, persistent banner, and safe exit."""

    def test_impersonate_tenant_owner_and_banner_flow(self, staff_user: User, org_one: Organization) -> None:
        client = Client(SERVER_NAME="acme-alpha.localhost")
        client.force_login(staff_user)

        # 1. Initiate impersonation of org_one
        resp_start = client.post(
            f"/backoffice/tenants/{org_one.public_id}/impersonate/",
            {"reason": "Troubleshooting billing and settings for customer"},
        )
        assert resp_start.status_code == 302
        assert resp_start.url == "/"

        # Session should hold impersonator details
        session = client.session
        assert session.get("impersonator_id") == staff_user.pk
        assert session.get("impersonator_email") == staff_user.email
        assert session.get("is_impersonating") is True

        # AuditLog entry for start
        audit_start = AuditLog.all_tenants.filter(
            organization=org_one, action="backoffice.impersonate_start"
        ).first()
        assert audit_start is not None
        assert audit_start.actor == staff_user
        assert "Troubleshooting" in audit_start.changes["reason"]

        # 2. Verify banner is rendered in subsequent requests
        resp_dash = client.get("/")
        assert resp_dash.status_code == 200
        html = resp_dash.content.decode()
        assert "STAFF IMPERSONATION:" in html
        assert "alpha_owner@example.com" in html
        assert "operator@bos.internal" in html
        assert "Exit Impersonation" in html

        # 3. Stop impersonation
        resp_stop = client.post("/backoffice/impersonate/stop/")
        assert resp_stop.status_code == 302
        assert resp_stop.url == "/backoffice/tenants/"

        # Session flags cleared
        session_after = client.session
        assert "impersonator_id" not in session_after

        # AuditLog entry for stop
        audit_stop = AuditLog.all_tenants.filter(
            organization=org_one, action="backoffice.impersonate_stop"
        ).first()
        assert audit_stop is not None
        assert audit_stop.actor == staff_user

        # Banner is gone
        resp_dash_clean = client.get("/")
        assert "STAFF IMPERSONATION:" not in resp_dash_clean.content.decode()

    def test_impersonate_specific_user(self, staff_user: User, org_two: Organization) -> None:
        client = Client()
        client.force_login(staff_user)

        target = User.objects.get(email="beta_owner@example.com")
        resp = client.post(
            f"/backoffice/impersonate/user/{target.id}/",
            {"reason": "Testing user specific permission profile"},
        )
        assert resp.status_code == 302

        session = client.session
        assert session.get("impersonator_id") == staff_user.pk


@pytest.mark.django_db
class TestBackofficeJobAndWebhookInspection:
    """Validate Outbox background jobs and webhook log inspection."""

    def test_outbox_list_and_retry_workflow(self, staff_user: User, org_one: Organization) -> None:
        # Create a failed outbox event
        failed_event = OutboxEvent.objects.create(
            organization=org_one,
            event_type="catalog.product_synced",
            payload={"product_id": "prod_123"},
            status=OutboxEvent.STATUS_FAILED,
            retry_count=2,
            last_error="ConnectionRefusedError: Remote webhook endpoint down",
        )

        client = Client()
        client.force_login(staff_user)

        # 1. List shows failed event
        resp_list = client.get("/backoffice/jobs/?status=failed")
        assert resp_list.status_code == 200
        html_list = resp_list.content.decode()
        assert "catalog.product_synced" in html_list
        assert str(failed_event.event_id) in html_list
        assert "ConnectionRefusedError" in html_list

        # 2. Detail shows full payload
        resp_detail = client.get(f"/backoffice/jobs/{failed_event.event_id}/")
        assert resp_detail.status_code == 200
        html_detail = resp_detail.content.decode()
        assert "catalog.product_synced" in html_detail
        assert "prod_123" in html_detail

        # 3. Retry event
        resp_retry = client.post(f"/backoffice/jobs/{failed_event.event_id}/retry/")
        assert resp_retry.status_code == 302

        failed_event.refresh_from_db()
        assert failed_event.status == OutboxEvent.STATUS_PENDING
        assert failed_event.retry_count == 3
        assert failed_event.last_error == ""

        # Audit log for retry
        audit = AuditLog.all_tenants.filter(organization=org_one, action="backoffice.outbox_retry").first()
        assert audit is not None
        assert audit.actor == staff_user

    def test_webhook_list_and_detail(self, staff_user: User) -> None:
        event = ProcessedWebhookEvent.objects.create(
            event_id="evt_stripe_test_12345",
            event_type="invoice.payment_succeeded",
            payload={
                "id": "evt_stripe_test_12345",
                "type": "invoice.payment_succeeded",
                "data": {"object": {"amount_paid": 5000}},
            },
        )

        client = Client()
        client.force_login(staff_user)

        # List
        resp_list = client.get("/backoffice/webhooks/")
        assert resp_list.status_code == 200
        assert "evt_stripe_test_12345" in resp_list.content.decode()

        # Detail
        resp_detail = client.get(f"/backoffice/webhooks/{event.event_id}/")
        assert resp_detail.status_code == 200
        assert "invoice.payment_succeeded" in resp_detail.content.decode()
        assert "amount_paid" in resp_detail.content.decode()
