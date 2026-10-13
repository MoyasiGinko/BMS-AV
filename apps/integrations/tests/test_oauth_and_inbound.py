"""Tests for OAuth2 provider and Inbound Webhook framework (P5-06)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from django.test import Client
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.integrations import services
from apps.integrations.models import (
    InboundSignatureAlgorithm,
    InboundWebhookEndpoint,
    InboundWebhookProvider,
    OAuthApplication,
)
from apps.tenancy.models import Membership, Organization, Role


@pytest.fixture
def org_owner(db: None) -> tuple[Organization, User]:
    org = Organization.objects.create(name="OAuth Org A", slug="oauth-org-a")
    user = User.objects.create_user(
        email="owner_a@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Admin",
        permissions=[
            "integrations.view",
            "integrations.manage",
            "integrations.oauth_manage",
            "integrations.inbound_manage",
        ],
    )
    Membership.objects.create(organization=org, user=user, role=role)
    return org, user


@pytest.fixture
def other_org_owner(db: None) -> tuple[Organization, User]:
    org = Organization.objects.create(name="OAuth Org B", slug="oauth-org-b")
    user = User.objects.create_user(
        email="owner_b@example.com",
        password="ValidPassword123!",
    )
    role = Role.objects.create(
        organization=org,
        name="Admin",
        permissions=[
            "integrations.view",
            "integrations.manage",
            "integrations.oauth_manage",
            "integrations.inbound_manage",
        ],
    )
    Membership.objects.create(organization=org, user=user, role=role)
    return org, user


@pytest.mark.django_db
class TestOAuthApplicationServices:
    """Test OAuth2 application registration and lifecycle services."""

    def test_create_oauth_application(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        app, raw_secret = services.create_oauth_application(
            organization=org,
            name="Zapier App",
            client_type="confidential",
            authorization_grant_type="client-credentials",
            allowed_scopes="read write",
            actor=user,
        )
        assert app.pk is not None
        assert app.organization == org
        assert app.name == "Zapier App"
        assert raw_secret is not None
        assert len(raw_secret) > 20
        # Ensure client_secret was hashed and not stored in plaintext
        assert app.client_secret != raw_secret
        assert app.client_id is not None

    def test_update_oauth_application(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        app, _ = services.create_oauth_application(
            organization=org,
            name="Mobile SPA",
            client_type="public",
            authorization_grant_type="authorization-code",
            allowed_scopes="read",
            actor=user,
        )
        updated = services.update_oauth_application(
            application=app,
            name="Renamed SPA",
            client_type="public",
            authorization_grant_type="authorization-code",
            redirect_uris="https://spa.example.com/callback",
            allowed_scopes="read write catalog:read",
            description="Mobile client",
            skip_authorization=True,
            actor=user,
        )
        assert updated.name == "Renamed SPA"
        assert updated.allowed_scopes == "read write catalog:read"
        assert updated.skip_authorization is True

    def test_rotate_oauth_client_secret(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        app, old_secret = services.create_oauth_application(
            organization=org,
            name="Server CLI",
            client_type="confidential",
            authorization_grant_type="client-credentials",
            actor=user,
        )
        old_hash = app.client_secret
        new_secret = services.rotate_oauth_client_secret(application=app, actor=user)
        app.refresh_from_db()

        assert new_secret != old_secret
        assert app.client_secret != old_hash

    def test_delete_oauth_application(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        app, _ = services.create_oauth_application(
            organization=org,
            name="Temporary App",
            client_type="confidential",
            authorization_grant_type="client-credentials",
            actor=user,
        )
        app_id = app.pk
        services.delete_oauth_application(application=app, actor=user)
        assert not OAuthApplication.objects.filter(pk=app_id).exists()


@pytest.mark.django_db
class TestInboundWebhookServices:
    """Test inbound webhook cryptographic signature verification and execution services."""

    def test_create_inbound_webhook_endpoint(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="Stripe Payments",
            provider=InboundWebhookProvider.STRIPE,
            signature_header="Stripe-Signature",
            signature_algorithm=InboundSignatureAlgorithm.HMAC_SHA256,
            secret="whsec_testsecret12345",
            target_event="payment.received",
            actor=user,
        )
        assert endpoint.pk is not None
        assert endpoint.organization == org
        assert endpoint.secret == "whsec_testsecret12345"
        assert endpoint.status == "active"

    def test_verify_generic_hmac_sha256(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        secret = "super_secret_signing_key_32bytes!"
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="Generic Rest Webhook",
            provider=InboundWebhookProvider.GENERIC,
            signature_header="X-Signature",
            signature_algorithm=InboundSignatureAlgorithm.HMAC_SHA256,
            secret=secret,
            actor=user,
        )

        body = b'{"event": "ping", "data": {"id": 123}}'
        computed_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        # Valid signature
        headers = {"X-Signature": computed_sig}
        valid, _ = services.verify_inbound_signature(endpoint=endpoint, raw_body=body, headers=headers)
        assert valid is True

        # Invalid signature
        bad_headers = {"X-Signature": "invalid_hex_string"}
        bad_valid, _ = services.verify_inbound_signature(
            endpoint=endpoint, raw_body=body, headers=bad_headers
        )
        assert bad_valid is False

    def test_verify_stripe_signature(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        secret = "whsec_stripe_test_secret"
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="Stripe Webhook",
            provider=InboundWebhookProvider.STRIPE,
            signature_header="Stripe-Signature",
            signature_algorithm=InboundSignatureAlgorithm.HMAC_SHA256,
            secret=secret,
            actor=user,
        )

        body = b'{"id": "evt_123", "type": "charge.succeeded"}'
        timestamp = str(int(time.time()))
        signed_payload = f"{timestamp}.".encode() + body
        sig_hash = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()

        header_val = f"t={timestamp},v1={sig_hash}"
        headers = {"Stripe-Signature": header_val}
        valid, _ = services.verify_inbound_signature(endpoint=endpoint, raw_body=body, headers=headers)
        assert valid is True

    def test_verify_github_signature(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        secret = "gh_secret_token"
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="GitHub Webhook",
            provider=InboundWebhookProvider.GITHUB,
            signature_header="X-Hub-Signature-256",
            signature_algorithm=InboundSignatureAlgorithm.HMAC_SHA256,
            secret=secret,
            actor=user,
        )

        body = b'{"ref": "refs/heads/main"}'
        sig_hash = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers = {"X-Hub-Signature-256": f"sha256={sig_hash}"}
        valid, _ = services.verify_inbound_signature(endpoint=endpoint, raw_body=body, headers=headers)
        assert valid is True

    def test_process_inbound_webhook_success(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        secret = "webhook_secret_key"
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="Inbound Listener",
            provider=InboundWebhookProvider.GENERIC,
            signature_header="X-Signature",
            signature_algorithm=InboundSignatureAlgorithm.HMAC_SHA256,
            secret=secret,
            target_event="inbound.received",
            actor=user,
        )

        body = json.dumps({"event": "order.completed", "order_id": 9999}).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers = {"X-Signature": sig, "Content-Type": "application/json"}

        log, is_valid = services.process_inbound_webhook(
            endpoint=endpoint,
            raw_body=body,
            headers=headers,
            ip_address="127.0.0.1",
        )
        assert is_valid is True
        assert log.verification_status == "verified"
        assert log.processing_status == "processed"
        assert log.endpoint == endpoint
        assert log.organization == org

        endpoint.refresh_from_db()
        assert endpoint.total_received_count == 1
        assert endpoint.last_received_at is not None

    def test_process_inbound_webhook_rejected(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="Reject Endpoint",
            provider=InboundWebhookProvider.GENERIC,
            secret="valid_secret",
            actor=user,
        )

        body = b'{"bad": "data"}'
        headers = {"X-Signature": "wrong_signature"}

        log, is_valid = services.process_inbound_webhook(
            endpoint=endpoint,
            raw_body=body,
            headers=headers,
            ip_address="1.2.3.4",
        )
        assert is_valid is False
        assert log.verification_status == "failed"
        err = (log.error_message or "").lower()
        assert "mismatch" in err or "failed" in err


@pytest.mark.django_db
class TestPublicInboundReceiverAPI:
    """Test public unauthenticated HTTP listener endpoint."""

    def test_public_receiver_endpoint(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        secret = "test_receiver_secret"
        endpoint = services.create_inbound_webhook_endpoint(
            organization=org,
            name="Public Receiver",
            provider=InboundWebhookProvider.GENERIC,
            signature_header="X-Signature",
            signature_algorithm=InboundSignatureAlgorithm.HMAC_SHA256,
            secret=secret,
            actor=user,
        )

        client = APIClient()
        url = reverse("api:inbound-webhook-receive", kwargs={"public_id": endpoint.public_id})

        body = json.dumps({"action": "ping"}).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        # Valid request
        resp = client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_SIGNATURE=sig,
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["status"] == "received"

        # Invalid signature
        bad_resp = client.post(
            url,
            data=body,
            content_type="application/json",
            HTTP_X_SIGNATURE="tampered_signature",
        )
        assert bad_resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert bad_resp.data["status"] == "rejected"


@pytest.mark.django_db
class TestOAuthAndInboundRESTAPI:
    """Test tenant scoped DRF ViewSets for OAuth applications and Inbound endpoints."""

    def test_oauth_application_crud_api(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        client = APIClient()
        client.force_authenticate(user=user)

        # Create
        create_resp = client.post(
            "/api/v1/integrations/oauth/applications/",
            data={
                "name": "Integration API Client",
                "client_type": "confidential",
                "authorization_grant_type": "client-credentials",
                "allowed_scopes": "read write",
            },
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert create_resp.status_code == status.HTTP_201_CREATED
        app_id = create_resp.data["id"]
        assert "client_secret" in create_resp.data

        # List
        list_resp = client.get(
            "/api/v1/integrations/oauth/applications/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert list_resp.status_code == status.HTTP_200_OK
        results = list_resp.data.get("results", list_resp.data)
        assert len(results) >= 1

        # Rotate secret
        rotate_resp = client.post(
            f"/api/v1/integrations/oauth/applications/{app_id}/rotate-secret/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert rotate_resp.status_code == status.HTTP_200_OK
        assert "new_secret" in rotate_resp.data

        # Delete
        del_resp = client.delete(
            f"/api/v1/integrations/oauth/applications/{app_id}/",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

    def test_cross_tenant_isolation(
        self,
        org_owner: tuple[Organization, User],
        other_org_owner: tuple[Organization, User],
    ) -> None:
        org_a, user_a = org_owner
        org_b, user_b = other_org_owner

        # Create in Org A
        app_a, _ = services.create_oauth_application(
            organization=org_a,
            name="App A",
            client_type="confidential",
            authorization_grant_type="client-credentials",
            actor=user_a,
        )
        ep_a = services.create_inbound_webhook_endpoint(organization=org_a, name="Inbound A", actor=user_a)

        # User B queries with Org B header
        client_b = APIClient()
        client_b.force_authenticate(user=user_b)

        app_b_resp = client_b.get(
            f"/api/v1/integrations/oauth/applications/{app_a.public_id}/",
            HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
        )
        assert app_b_resp.status_code == status.HTTP_404_NOT_FOUND

        ep_b_resp = client_b.get(
            f"/api/v1/integrations/inbound/endpoints/{ep_a.public_id}/",
            HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
        )
        assert ep_b_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestOAuthAndInboundWebUI:
    """Test full server-rendered HTML views and HTMX partials."""

    def test_oauth_applications_web_flow(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        client = Client()
        client.force_login(user)

        # List
        resp = client.get(
            reverse("integrations:oauth_applications_list"),
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert resp.status_code == 200

        # Create
        create_resp = client.post(
            reverse("integrations:oauth_application_create"),
            data={
                "name": "Portal Frontend",
                "client_type": "public",
                "authorization_grant_type": "authorization-code",
                "redirect_uris": "https://portal.example.com/oauth/callback",
                "scopes": ["read", "write"],
            },
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert create_resp.status_code == 200
        assert b"Save Your Client Secret Now!" in create_resp.content

        app = OAuthApplication.objects.get(name="Portal Frontend")

        # Detail
        detail_resp = client.get(
            reverse("integrations:oauth_application_detail", kwargs={"app_id": app.public_id}),
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert detail_resp.status_code == 200

        # HTMX Rotate secret
        rotate_resp = client.post(
            reverse("integrations:oauth_application_rotate_secret", kwargs={"app_id": app.public_id}),
            HTTP_HX_REQUEST="true",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert rotate_resp.status_code == 200
        assert b"Secret rotated successfully!" in rotate_resp.content

    def test_inbound_endpoints_web_flow(self, org_owner: tuple[Organization, User]) -> None:
        org, user = org_owner
        client = Client()
        client.force_login(user)

        # List
        resp = client.get(
            reverse("integrations:inbound_endpoints_list"),
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert resp.status_code == 200

        # Create
        create_resp = client.post(
            reverse("integrations:inbound_endpoint_create"),
            data={
                "name": "Shopify Order Webhooks",
                "provider": "shopify",
                "signature_header": "X-Shopify-Hmac-Sha256",
                "signature_algorithm": "hmac_sha256",
                "target_event": "shopify.order.created",
                "status": "active",
            },
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert create_resp.status_code == 302

        ep = InboundWebhookEndpoint.all_tenants.get(name="Shopify Order Webhooks")

        # Detail
        detail_resp = client.get(
            reverse("integrations:inbound_endpoint_detail", kwargs={"endpoint_id": ep.public_id}),
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert detail_resp.status_code == 200
        assert b"Shopify Order Webhooks" in detail_resp.content

        # HTMX Rotate secret
        rotate_resp = client.post(
            reverse("integrations:inbound_endpoint_rotate_secret", kwargs={"endpoint_id": ep.public_id}),
            HTTP_HX_REQUEST="true",
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert rotate_resp.status_code == 200
        assert b"Secret rotated!" in rotate_resp.content

        # Global logs list
        logs_resp = client.get(
            reverse("integrations:inbound_logs_list"),
            HTTP_X_ORGANIZATION_ID=str(org.public_id),
        )
        assert logs_resp.status_code == 200
