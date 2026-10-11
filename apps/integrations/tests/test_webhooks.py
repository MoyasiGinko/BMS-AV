"""Comprehensive test suite for Webhooks v1.

Covers:
1. Event Catalog completeness for P1-P3 domain events.
2. Cryptographic signing, replay window tolerance, and signature verification.
3. Endpoint CRUD, subscription filtering, secret rotation, and test pings.
4. HTTP delivery execution, exponential backoff retries, and auto-disabling on failure.
5. Manual redelivery workflow.
6. Tenant isolation and three-layer permissions.
7. Versioned REST API endpoints under /api/v1/integrations/webhooks/.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.billing.services import seed_default_plans
from apps.core.event_catalog import (
    get_event_definition,
    list_event_catalog,
    list_events_by_module,
)
from apps.integrations import selectors, services
from apps.integrations.models import (
    WebhookDelivery,
    WebhookDeliveryStatus,
)
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import provision_organization

User = get_user_model()


class MockHttpResponse:
    """Mock HTTP response for testing webhook delivery."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = '{"received": true}',
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {"content-type": "application/json"}


class MockHttpClient:
    """Mock HTTP client adapter."""

    def __init__(
        self,
        status_code: int = 200,
        text: str = '{"ok": true}',
        raise_exc: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.raise_exc = raise_exc
        self.last_request: dict[str, Any] | None = None

    def post(
        self,
        url: str,
        *,
        content: bytes,
        headers: dict[str, str],
        timeout: float = 10.0,
    ) -> MockHttpResponse:
        self.last_request = {
            "url": url,
            "content": content,
            "headers": headers,
            "timeout": timeout,
        }
        if self.raise_exc:
            raise self.raise_exc
        return MockHttpResponse(status_code=self.status_code, text=self.text)


@pytest.fixture
def webhook_env(db: None) -> dict[str, Any]:
    """Setup organizations, roles, and users for webhook testing."""
    seed_default_plans()
    owner = User.objects.create_user(email="wh_owner@test.org", password="password123")
    org_a = provision_organization(name="Alpha Corp", slug="alpha-corp", owner=owner, plan="enterprise")

    # Viewer user (read-only integrations)
    viewer_user = User.objects.create_user(email="wh_viewer@test.org", password="password123")
    role_viewer = Role.all_tenants.filter(organization=org_a, name="Viewer").first()
    assert role_viewer is not None
    Membership.objects.create(
        organization=org_a,
        user=viewer_user,
        role=role_viewer,
        status=Membership.STATUS_ACTIVE,
    )

    # Competitor Org B
    owner_b = User.objects.create_user(email="wh_rival@test.org", password="password123")
    org_b = provision_organization(name="Beta Corp", slug="beta-corp", owner=owner_b, plan="enterprise")

    return {
        "org_a": org_a,
        "owner": owner,
        "viewer_user": viewer_user,
        "org_b": org_b,
        "owner_b": owner_b,
    }


@pytest.mark.django_db
class TestEventCatalogCompleteness:
    """Verify event catalog contains all required P1-P3 events with metadata."""

    def test_minimum_catalog_events_present(self) -> None:
        required_events = [
            # P1 Core & Tenancy
            "organization.created",
            "member.invited",
            "member.joined",
            "audit.logged",
            # P2 Catalog & Inventory
            "catalog.product_created",
            "product.created",
            "inventory.stock_received",
            "inventory.stock_adjusted",
            "stock.low",
            # P2 Customers & Sales
            "customers.customer_created",
            "customer.created",
            "sales.order_created",
            "sales.order_confirmed",
            "sales.invoice_created",
            "sales.invoice_posted",
            "sales.invoice_voided",
            "invoice.created",
            "invoice.posted",
            "invoice.paid",
            "sales.payment_received",
            "payment.received",
            # P2 POS
            "pos.shift_opened",
            "pos.shift_closed",
            "pos.sale_completed",
            # P3 Purchasing
            "purchasing.supplier_created",
            "purchasing.po_created",
            "purchasing.po_approved",
            "purchasing.goods_receipt_created",
            "purchasing.bill_posted",
            "purchasing.payment_recorded",
            "purchase.received",
            # P3 Accounting
            "accounting.entry_posted",
            "accounting.entry_reversed",
            "accounting.expense_created",
            "accounting.expense_posted",
            "accounting.period_closed",
            "expense.created",
            # Billing
            "subscription.created",
            "subscription.changed",
            "subscription.canceled",
            # Integrations
            "webhook.ping",
        ]

        all_events = {defn.event_type for defn in list_event_catalog()}
        for req in required_events:
            assert req in all_events, f"Required event {req} missing from event catalog!"
            defn = get_event_definition(req)
            assert defn is not None
            assert len(defn.description) > 5

    def test_events_by_module_grouping(self) -> None:
        grouped = list_events_by_module()
        assert "sales" in grouped
        assert "inventory" in grouped
        assert "accounting" in grouped
        assert "purchasing" in grouped
        assert len(grouped["sales"]) >= 5


@pytest.mark.django_db
class TestWebhookSigningAndVerification:
    """Verify HMAC-SHA256 signature computation and replay tolerance."""

    def test_signature_computation_matches_standard(self) -> None:
        secret = "whsec_test_secret_key_12345"
        timestamp = 1700000000
        payload_str = '{"event":"invoice.posted","id":100}'

        sig = services.compute_webhook_signature(secret, timestamp, payload_str)
        assert sig.startswith("sha256=")
        assert len(sig) == 7 + 64  # 'sha256=' + 64-character hex digest

        # Verify signature validator accepts it
        assert services.verify_webhook_signature(secret, timestamp, payload_str, sig, tolerance=1000000000)

    def test_replay_window_tolerance(self) -> None:
        secret = "whsec_secret"
        now = int(timezone.now().timestamp())
        payload = '{"test":1}'
        sig = services.compute_webhook_signature(secret, now, payload)

        # Fresh timestamp: valid
        assert services.verify_webhook_signature(secret, now, payload, sig, tolerance=300)

        # 10 minutes ago: rejected due to 5-minute (300s) replay window
        old_timestamp = now - 600
        old_sig = services.compute_webhook_signature(secret, old_timestamp, payload)
        assert not services.verify_webhook_signature(secret, old_timestamp, payload, old_sig, tolerance=300)

        # Altered payload: rejected
        assert not services.verify_webhook_signature(secret, now, '{"test":2}', sig, tolerance=300)


@pytest.mark.django_db
class TestWebhookEndpointsAndSubscriptions:
    """Test endpoint CRUD, subscription matching, and secret rotation."""

    def test_create_and_update_endpoint(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        owner = webhook_env["owner"]

        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://hooks.example.com/events",
            events=["invoice.posted", "payment.received"],
            description="Zapier Accounting Flow",
            actor=owner,
        )

        assert endpoint.pk is not None
        assert endpoint.url == "https://hooks.example.com/events"
        assert endpoint.secret.startswith("whsec_")
        assert endpoint.events == ["invoice.posted", "payment.received"]
        assert endpoint.is_active is True
        assert endpoint.consecutive_failures == 0

        # Update
        updated = services.update_webhook_endpoint(
            endpoint=endpoint,
            url="https://hooks.example.com/v2/events",
            events=["*"],
            description="Updated Zapier Flow",
            is_active=False,
            actor=owner,
        )
        assert updated.url == "https://hooks.example.com/v2/events"
        assert updated.events == ["*"]
        assert updated.is_active is False

    def test_invalid_url_rejected(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        with pytest.raises(ValueError, match="http"):
            services.create_webhook_endpoint(
                organization=org,
                url="ftp://invalid-url.com",
            )

    def test_rotate_secret(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://hooks.example.com/listener",
        )
        old_secret = endpoint.secret

        rotated = services.rotate_webhook_secret(endpoint=endpoint)
        assert rotated.secret != old_secret
        assert rotated.secret.startswith("whsec_")


@pytest.mark.django_db
class TestWebhookDeliveryLifecycle:
    """Test fanout, HTTP delivery execution, retries, and auto-disabling."""

    def test_event_fanout_to_matching_endpoints(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]

        # Endpoint 1: Subscribed to invoice.*
        ep1 = services.create_webhook_endpoint(
            organization=org,
            url="https://hooks.test.com/invoices",
            events=["invoice.*"],
        )
        # Endpoint 2: Subscribed to all (*)
        ep2 = services.create_webhook_endpoint(
            organization=org,
            url="https://hooks.test.com/all",
            events=["*"],
        )
        # Endpoint 3: Subscribed only to payment.received
        ep3 = services.create_webhook_endpoint(
            organization=org,
            url="https://hooks.test.com/payments",
            events=["payment.received"],
        )

        # Dispatch an invoice.posted event
        deliveries = services.dispatch_event_to_webhooks(
            event_type="invoice.posted",
            event_id="evt_101",
            payload={"invoice_number": "INV-001", "amount": "500.00"},
            organization_id=org.pk,
        )

        # ep1 (invoice.*) and ep2 (*) must match, ep3 must not
        assert len(deliveries) == 2
        matched_endpoints = {d.endpoint_id for d in deliveries}
        assert ep1.pk in matched_endpoints
        assert ep2.pk in matched_endpoints
        assert ep3.pk not in matched_endpoints

    def test_successful_http_delivery(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://external-api.test/webhook",
            events=["*"],
        )

        delivery = WebhookDelivery.objects.create(
            organization=org,
            endpoint=endpoint,
            event_type="invoice.posted",
            event_id="evt_202",
            payload={"invoice_id": 42},
            status=WebhookDeliveryStatus.PENDING,
        )

        client = MockHttpClient(status_code=200, text='{"success": true}')
        delivered = services.deliver_webhook(delivery=delivery, http_client=client)

        assert delivered.status == WebhookDeliveryStatus.SUCCESS
        assert delivered.response_status_code == 200
        assert delivered.delivered_at is not None
        assert delivered.next_retry_at is None
        assert delivered.execution_time_ms >= 1
        assert "X-Signature" in delivered.request_headers
        assert "X-Timestamp" in delivered.request_headers
        assert delivered.request_headers["X-BusinessOS-Event"] == "invoice.posted"

    def test_failed_delivery_exponential_backoff_and_retry(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://broken-server.test/webhook",
            events=["*"],
        )

        delivery = WebhookDelivery.objects.create(
            organization=org,
            endpoint=endpoint,
            event_type="payment.received",
            event_id="evt_fail_1",
            payload={"payment_id": 99},
            status=WebhookDeliveryStatus.PENDING,
            attempt=1,
        )

        # Attempt 1: Server errors 500
        client = MockHttpClient(status_code=500, text="Internal Server Error")
        delivered = services.deliver_webhook(delivery=delivery, http_client=client)

        assert delivered.status == WebhookDeliveryStatus.RETRYING
        assert delivered.response_status_code == 500
        assert delivered.next_retry_at is not None
        assert delivered.next_retry_at > timezone.now()
        assert endpoint.consecutive_failures == 1

        # Attempt 5: Final failure
        delivered.attempt = 5
        services.deliver_webhook(delivery=delivered, http_client=client)
        assert delivered.status == WebhookDeliveryStatus.FAILED
        assert delivered.next_retry_at is None

    def test_endpoint_auto_disabled_after_10_failures(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://dead-endpoint.test/webhook",
        )
        endpoint.consecutive_failures = 9
        endpoint.save()

        delivery = WebhookDelivery.objects.create(
            organization=org,
            endpoint=endpoint,
            event_type="invoice.created",
            event_id="evt_dead",
            payload={},
            status=WebhookDeliveryStatus.PENDING,
        )

        client = MockHttpClient(raise_exc=ConnectionError("Host unreachable"))
        services.deliver_webhook(delivery=delivery, http_client=client)

        endpoint.refresh_from_db()
        assert endpoint.consecutive_failures == 10
        assert endpoint.is_active is False
        assert endpoint.disabled_at is not None

    def test_manual_redelivery(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://recovered-endpoint.test/webhook",
        )
        delivery = WebhookDelivery.objects.create(
            organization=org,
            endpoint=endpoint,
            event_type="product.created",
            event_id="evt_redeliver",
            payload={"sku": "PROD-1"},
            status=WebhookDeliveryStatus.FAILED,
            attempt=5,
        )

        client = MockHttpClient(status_code=200, text="OK")
        redelivered = services.redeliver_webhook(delivery=delivery, http_client=client)

        assert redelivered.status == WebhookDeliveryStatus.SUCCESS
        assert redelivered.attempt == 6
        assert redelivered.response_status_code == 200

    def test_send_test_ping(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://ping.test/webhook",
        )

        client = MockHttpClient(status_code=200, text='{"pong": true}')
        ping_deliv = services.send_test_ping(endpoint=endpoint, http_client=client)

        assert ping_deliv.event_type == "webhook.ping"
        assert ping_deliv.status == WebhookDeliveryStatus.SUCCESS
        assert ping_deliv.payload["event"] == "webhook.ping"


@pytest.mark.django_db
class TestWebhookTenantIsolationAndPermissions:
    """Ensure strict tenant isolation and role permission enforcement."""

    def test_cross_tenant_isolation(self, webhook_env: dict[str, Any]) -> None:
        org_a = webhook_env["org_a"]
        org_b = webhook_env["org_b"]

        # Org B registers an endpoint
        ep_b = services.create_webhook_endpoint(
            organization=org_b,
            url="https://rival.test/events",
            events=["*"],
        )

        # Org A selectors must NOT see Org B endpoint
        endpoints_a = selectors.list_webhook_endpoints(org_a)
        assert ep_b not in endpoints_a

        # Org A event must NOT trigger Org B endpoint
        deliveries = services.dispatch_event_to_webhooks(
            event_type="invoice.posted",
            event_id="evt_org_a",
            payload={"total": "100"},
            organization_id=org_a.pk,
        )
        for d in deliveries:
            assert d.endpoint.organization_id == org_a.pk
            assert d.endpoint_id != ep_b.pk

    def test_role_permissions_enforcement(self, webhook_env: dict[str, Any]) -> None:
        org = webhook_env["org_a"]
        viewer = webhook_env["viewer_user"]
        owner = webhook_env["owner"]

        endpoint = services.create_webhook_endpoint(
            organization=org,
            url="https://perms.test/webhook",
            actor=owner,
        )

        client = Client()

        # Viewer can view list and detail
        client.force_login(viewer)
        res_list = client.get("/integrations/webhooks/")
        assert res_list.status_code == 200

        res_detail = client.get(f"/integrations/webhooks/{endpoint.public_id}/")
        assert res_detail.status_code == 200

        # Viewer cannot create endpoint (requires integrations.manage)
        res_create = client.post(
            "/integrations/webhooks/new/",
            {"url": "https://hack.test/wh", "selected_events": ["*"]},
        )
        assert res_create.status_code == 403

        # Viewer cannot rotate secret
        res_rotate = client.post(f"/integrations/webhooks/{endpoint.public_id}/rotate-secret/")
        assert res_rotate.status_code == 403


@pytest.mark.django_db
class TestWebhookRestApiEndpoints:
    """Verify REST API v1 viewset endpoints under /api/v1/integrations/webhooks/."""

    def test_api_crud_and_actions(self, webhook_env: dict[str, Any]) -> None:
        owner = webhook_env["owner"]

        client = APIClient()
        client.force_authenticate(user=owner)

        # 1. Create Endpoint via API
        create_payload = {
            "url": "https://api-subscriber.test/v1/webhook",
            "description": "External ERP Sync",
            "events": ["invoice.posted", "payment.received"],
            "is_active": True,
        }
        res_create = client.post("/api/v1/integrations/webhooks/", create_payload, format="json")
        assert res_create.status_code == status.HTTP_201_CREATED
        data = res_create.json()
        ep_id = data["id"]
        assert data["url"] == "https://api-subscriber.test/v1/webhook"
        assert "secret" in data
        assert data["secret"].startswith("whsec_")

        # 2. List Endpoints
        res_list = client.get("/api/v1/integrations/webhooks/")
        assert res_list.status_code == status.HTTP_200_OK
        assert len(res_list.json()) >= 1

        # 3. Retrieve Endpoint
        res_get = client.get(f"/api/v1/integrations/webhooks/{ep_id}/")
        assert res_get.status_code == status.HTTP_200_OK
        assert res_get.json()["id"] == ep_id

        # 4. Rotate Secret via API
        res_rotate = client.post(f"/api/v1/integrations/webhooks/{ep_id}/rotate-secret/")
        assert res_rotate.status_code == status.HTTP_200_OK
        new_secret = res_rotate.json()["secret"]
        assert new_secret != data["secret"]

        # 5. Send Test Ping via API
        res_ping = client.post(f"/api/v1/integrations/webhooks/{ep_id}/ping/")
        assert res_ping.status_code == status.HTTP_200_OK
        ping_data = res_ping.json()
        assert "delivery_id" in ping_data

        # 6. List Deliveries for Endpoint
        res_delivs = client.get(f"/api/v1/integrations/webhooks/{ep_id}/deliveries/")
        assert res_delivs.status_code == status.HTTP_200_OK
        assert len(res_delivs.json()) >= 1
        delivery_id = ping_data["delivery_id"]

        # 7. Redeliver via API
        res_redeliv = client.post(f"/api/v1/integrations/webhooks/deliveries/{delivery_id}/redeliver/")
        assert res_redeliv.status_code == status.HTTP_200_OK
        assert res_redeliv.json()["attempt"] >= 2

        # 8. Delete Endpoint
        res_del = client.delete(f"/api/v1/integrations/webhooks/{ep_id}/")
        assert res_del.status_code == status.HTTP_204_NO_CONTENT
