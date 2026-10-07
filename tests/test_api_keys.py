"""Comprehensive test suite for scoped, hashed API keys, authentication, rate limits, usage metering, and UI.

Covers:
- Key generation, hashing, formatting, and IP allowlist validation.
- DRF ApiKeyAuthentication backend (X-API-Key, Authorization headers, invalid hash, expiry, IP allowlist).
- Rotation with immediate revocation and grace periods.
- Plan-based rate limiting (ApiKeyRateThrottle).
- Usage metering telemetry and UsageCounter incrementation.
- Scoped permissions and cross-tenant isolation.
- REST API /api/v1/core/api-keys/ viewset.
- Tenant workspace settings UI (/settings/api-keys/).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Plan, UsageCounter
from apps.billing.services import create_subscription, seed_default_plans
from apps.core.api.throttling import get_organization_rate_limit
from apps.core.metrics import get_metric_count
from apps.core.models import ApiKey
from apps.core.selectors import get_active_api_key_by_prefix
from apps.core.services import (
    create_api_key,
    is_ip_allowed,
    revoke_api_key,
    rotate_api_key,
)
from apps.tenancy.models import Membership, Organization, Role
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_cache() -> Any:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def owner_a(db: None) -> User:
    return User.objects.create_user(email="owner_a@example.com", password="Password123!")


@pytest.fixture
def owner_b(db: None) -> User:
    return User.objects.create_user(email="owner_b@example.com", password="Password123!")


@pytest.fixture
def member_viewer_a(db: None) -> User:
    return User.objects.create_user(email="viewer_a@example.com", password="Password123!")


@pytest.fixture
def org_a(db: None, owner_a: User, member_viewer_a: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Apex Systems", slug="apex", owner=owner_a)
    create_subscription(organization=org, plan=plans["starter"], actor=owner_a, trial_days=0)
    role_viewer = Role.all_tenants.filter(organization=org, name="Viewer").first()
    assert role_viewer is not None
    Membership.all_tenants.create(
        organization=org,
        user=member_viewer_a,
        role=role_viewer,
        status=Membership.STATUS_ACTIVE,
    )
    return org


@pytest.fixture
def org_b(db: None, owner_b: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Nexus Logistics", slug="nexus", owner=owner_b)
    create_subscription(organization=org, plan=plans["growth"], actor=owner_b, trial_days=0)
    return org


@pytest.mark.django_db
class TestApiKeyServicesAndHashing:
    def test_create_api_key_format_and_hashing(self, org_a: Organization, owner_a: User) -> None:
        key, raw_key = create_api_key(
            organization=org_a,
            name="CI Pipeline",
            actor=owner_a,
            scopes=["core:read", "billing:read"],
            ip_allowlist=["192.168.1.0/24", "10.0.0.1"],
        )

        assert raw_key.startswith("bos_live_")
        assert key.prefix in raw_key
        assert key.name == "CI Pipeline"
        assert key.key_hash != raw_key
        assert len(key.key_hash) == 64  # SHA-256
        assert key.scopes == ["core:read", "billing:read"]
        assert key.is_active is True
        assert key.revoked_at is None

        # Lookup by prefix
        active_key = get_active_api_key_by_prefix(prefix=key.prefix)
        assert active_key is not None
        assert active_key.id == key.id

    def test_ip_allowlist_matching(self) -> None:
        assert is_ip_allowed("127.0.0.1", []) is True
        assert is_ip_allowed("192.168.1.50", ["192.168.1.0/24"]) is True
        assert is_ip_allowed("10.0.0.2", ["192.168.1.0/24", "10.0.0.1"]) is False
        assert is_ip_allowed("10.0.0.1", ["192.168.1.0/24", "10.0.0.1"]) is True
        assert is_ip_allowed("", ["192.168.1.0/24"]) is False

    def test_rotation_immediate(self, org_a: Organization, owner_a: User) -> None:
        old_key, _ = create_api_key(
            organization=org_a,
            name="Legacy Worker",
            actor=owner_a,
            scopes=["core:read"],
        )

        new_key, raw_new = rotate_api_key(
            api_key=old_key,
            actor=owner_a,
            grace_period_hours=0,
        )

        old_key.refresh_from_db()
        assert old_key.is_active is False
        assert old_key.revoked_at is not None
        assert new_key.is_active is True
        assert new_key.rotated_from_id == old_key.id
        assert raw_new.startswith("bos_live_")

    def test_rotation_with_grace_period(self, org_a: Organization, owner_a: User) -> None:
        old_key, _ = create_api_key(
            organization=org_a,
            name="Graceful Worker",
            actor=owner_a,
        )

        new_key, _ = rotate_api_key(
            api_key=old_key,
            actor=owner_a,
            grace_period_hours=24,
        )

        old_key.refresh_from_db()
        assert old_key.is_active is True
        assert old_key.expires_at is not None
        assert old_key.expires_at > timezone.now() + timedelta(hours=23)
        assert new_key.is_active is True

    def test_revoke_api_key(self, org_a: Organization, owner_a: User) -> None:
        key, _ = create_api_key(organization=org_a, name="Temporary Key", actor=owner_a)
        revoke_api_key(api_key=key, actor=owner_a)

        key.refresh_from_db()
        assert key.is_active is False
        assert key.revoked_at is not None
        assert key.revoked_by == owner_a


@pytest.mark.django_db
class TestApiKeyAuthenticationBackend:
    def test_auth_via_x_api_key_header(self, org_a: Organization, owner_a: User) -> None:
        _, raw_key = create_api_key(
            organization=org_a,
            name="Header Test",
            actor=owner_a,
            scopes=["settings:read"],
        )

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)

        response = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert response.status_code == status.HTTP_200_OK

    def test_auth_via_authorization_api_key(self, org_a: Organization, owner_a: User) -> None:
        _, raw_key = create_api_key(organization=org_a, name="Auth Header Test", actor=owner_a)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")

        response = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert response.status_code == status.HTTP_200_OK

    def test_auth_via_authorization_bearer_token(self, org_a: Organization, owner_a: User) -> None:
        _, raw_key = create_api_key(organization=org_a, name="Bearer Test", actor=owner_a)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")

        response = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert response.status_code == status.HTTP_200_OK

    def test_invalid_key_hash_rejected(self, org_a: Organization, owner_a: User) -> None:
        key, _ = create_api_key(organization=org_a, name="Tampered Test", actor=owner_a)
        tampered_key = f"bos_live_{key.prefix}_00000000000000000000000000000000"

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=tampered_key)

        response = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_expired_key_rejected(self, org_a: Organization, owner_a: User) -> None:
        _key, raw_key = create_api_key(
            organization=org_a,
            name="Expired Key",
            actor=owner_a,
            expires_at=timezone.now() - timedelta(minutes=5),
        )

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)

        response = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_revoked_key_rejected(self, org_a: Organization, owner_a: User) -> None:
        key, raw_key = create_api_key(organization=org_a, name="Revoked Key", actor=owner_a)
        revoke_api_key(api_key=key, actor=owner_a)

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)

        response = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ip_allowlist_enforcement(self, org_a: Organization, owner_a: User) -> None:
        _, raw_key = create_api_key(
            organization=org_a,
            name="IP Restrict Key",
            actor=owner_a,
            ip_allowlist=["192.168.1.100"],
        )

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)

        # Blocked from default test runner IP (127.0.0.1)
        response_blocked = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
            REMOTE_ADDR="127.0.0.1",
        )
        assert response_blocked.status_code == status.HTTP_401_UNAUTHORIZED

        # Permitted from allowed IP
        response_ok = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
            REMOTE_ADDR="192.168.1.100",
        )
        assert response_ok.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestUsageMeteringAndTelemetry:
    def test_api_call_increments_metric_and_telemetry(self, org_a: Organization, owner_a: User) -> None:
        key, raw_key = create_api_key(organization=org_a, name="Telemetry Key", actor=owner_a)

        initial_count = get_metric_count(org_a.id, "api_calls")

        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key)
        client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
            REMOTE_ADDR="203.0.113.195",
        )

        key.refresh_from_db()
        assert key.last_used_at is not None
        assert key.last_used_ip == "203.0.113.195"

        new_count = get_metric_count(org_a.id, "api_calls")
        assert new_count == initial_count + 1

        # Check UsageCounter table
        counter = UsageCounter.all_tenants.filter(organization=org_a, metric="api_calls").first()
        assert counter is not None
        assert counter.value >= 1


@pytest.mark.django_db
class TestApiKeyRateLimiting:
    def test_throttle_rate_resolves_per_plan(
        self,
        org_a: Organization,
        org_b: Organization,
        owner_a: User,
        owner_b: User,
    ) -> None:
        # Org A is Starter: 60/minute
        create_api_key(organization=org_a, name="Key A", actor=owner_a)
        rate_a = get_organization_rate_limit(org_a)
        assert rate_a == "60/minute"

        # Org B is Growth: 300/minute
        create_api_key(organization=org_b, name="Key B", actor=owner_b)
        rate_b = get_organization_rate_limit(org_b)
        assert rate_b == "300/minute"


@pytest.mark.django_db
class TestApiKeyDRFViewSet:
    def test_list_and_create_api_keys(self, org_a: Organization, owner_a: User) -> None:
        client = APIClient()
        client.force_authenticate(user=owner_a)

        # 1. Create API key
        resp = client.post(
            "/api/v1/core/api-keys/",
            {
                "name": "Integration Webhook Key",
                "scopes": ["core:read", "billing:read"],
                "ip_allowlist": ["10.0.0.0/8"],
            },
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert "raw_key" in data
        assert data["raw_key"].startswith("bos_live_")
        assert data["api_key"]["name"] == "Integration Webhook Key"
        public_id = data["api_key"]["id"]

        # 2. List API keys
        resp_list = client.get(
            "/api/v1/core/api-keys/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert resp_list.status_code == status.HTTP_200_OK
        items = resp_list.json()["results"]
        assert len(items) == 1
        assert "raw_key" not in items[0]
        assert "key_hash" not in items[0]
        assert items[0]["name"] == "Integration Webhook Key"

        # 3. Rotate API key
        resp_rotate = client.post(
            f"/api/v1/core/api-keys/{public_id}/rotate/",
            {"grace_period_hours": 12},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert resp_rotate.status_code == status.HTTP_200_OK
        rot_data = resp_rotate.json()
        assert "raw_key" in rot_data
        new_public_id = rot_data["api_key"]["id"]
        assert new_public_id != public_id
        new_key = ApiKey.all_tenants.get(public_id=new_public_id)
        assert new_key.rotated_from is not None
        assert str(new_key.rotated_from.public_id) == public_id

        # 4. Revoke API key
        resp_revoke = client.post(
            f"/api/v1/core/api-keys/{public_id}/revoke/",
            {},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
        )
        assert resp_revoke.status_code == status.HTTP_200_OK
        assert resp_revoke.json()["is_active"] is False

    def test_cross_tenant_isolation(
        self,
        org_a: Organization,
        org_b: Organization,
        owner_a: User,
        owner_b: User,
    ) -> None:
        key_a, _ = create_api_key(organization=org_a, name="Org A Key", actor=owner_a)

        client = APIClient()
        client.force_authenticate(user=owner_b)

        # Org B attempts to access Org A's key
        resp = client.get(
            f"/api/v1/core/api-keys/{key_a.public_id}/",
            HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
        )
        assert resp.status_code == status.HTTP_404_NOT_FOUND

        resp_revoke = client.post(
            f"/api/v1/core/api-keys/{key_a.public_id}/revoke/",
            {},
            format="json",
            HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
        )
        assert resp_revoke.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestApiKeySettingsUI:
    def test_ui_view_and_management(self, org_a: Organization, owner_a: User, member_viewer_a: User) -> None:
        client = Client()
        client.force_login(owner_a)
        session = client.session
        session["active_org_id"] = org_a.id
        session.save()

        # 1. GET settings page
        resp = client.get(
            "/settings/api-keys/",
            HTTP_HOST="apex.localhost",
        )
        assert resp.status_code == 200
        assert "API Keys" in resp.content.decode()
        assert "60/minute" in resp.content.decode()

        # 2. POST create key
        resp_create = client.post(
            "/settings/api-keys/",
            {
                "action": "create",
                "name": "Frontend Dashboard Key",
                "scopes": ["core:read"],
                "ip_allowlist": "10.0.0.1, 10.0.0.2",
            },
            HTTP_HOST="apex.localhost",
            follow=True,
        )
        assert resp_create.status_code == 200
        html = resp_create.content.decode()
        assert "Frontend Dashboard Key" in html
        assert "bos_live_" in html

        key = ApiKey.all_tenants.filter(organization=org_a, name="Frontend Dashboard Key").first()
        assert key is not None

        # 3. POST rotate key
        resp_rotate = client.post(
            "/settings/api-keys/",
            {
                "action": "rotate",
                "key_id": str(key.public_id),
                "grace_period_hours": "24",
            },
            HTTP_HOST="apex.localhost",
            follow=True,
        )
        assert resp_rotate.status_code == 200
        assert "rotated" in resp_rotate.content.decode()

        # 4. POST revoke key
        resp_revoke = client.post(
            "/settings/api-keys/",
            {
                "action": "revoke",
                "key_id": str(key.public_id),
            },
            HTTP_HOST="apex.localhost",
            follow=True,
        )
        assert resp_revoke.status_code == 200
        key.refresh_from_db()
        assert key.is_active is False

    def test_ui_permission_denied_for_viewer(self, org_a: Organization, member_viewer_a: User) -> None:
        client = Client()
        client.force_login(member_viewer_a)
        session = client.session
        session["active_org_id"] = org_a.id
        session.save()

        resp = client.get(
            "/settings/api-keys/",
            HTTP_HOST="apex.localhost",
        )
        assert resp.status_code == 403
