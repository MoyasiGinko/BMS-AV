"""Contract tests for DRF foundation:

- JWT auth: token obtain, refresh, verify, bearer token usage.
- Request-ID middleware & error response tracing.
- TenantScopedViewSet & cross-tenant isolation.
- 3-Layer authorization (plan entitlement, role permission).
- Cursor pagination.
- Idempotency key caching, replay, and payload mismatch detection.
- Unified exception handler response formatting.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import NumberSequence
from apps.core.permissions import clear_feature_overrides, set_feature_override
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_state() -> None:
    cache.clear()
    clear_feature_overrides()
    yield
    cache.clear()
    clear_feature_overrides()


@pytest.fixture
def api_setup(db: None) -> dict[str, object]:
    user_a = User.objects.create_user(email="tenant_a_admin@example.com", password="Password123!")
    user_b = User.objects.create_user(email="tenant_b_admin@example.com", password="Password123!")
    user_viewer = User.objects.create_user(email="tenant_a_viewer@example.com", password="Password123!")

    org_a = create_organization(name="Acme Corp", slug="acme", owner=user_a)
    org_b = create_organization(name="Beta LLC", slug="beta", owner=user_b)

    role_viewer = Role.all_tenants.filter(organization=org_a, name="Viewer").first()
    assert role_viewer is not None
    Membership.all_tenants.create(
        organization=org_a,
        user=user_viewer,
        role=role_viewer,
        status=Membership.STATUS_ACTIVE,
    )

    with tenant_context(org_a):
        seq_a = NumberSequence.objects.get(
            organization=org_a,
            name="Invoices",
        )

    with tenant_context(org_b):
        seq_b = NumberSequence.objects.get(
            organization=org_b,
            name="Invoices",
        )
        seq_b.prefix = "BETA-"
        seq_b.save(update_fields=["prefix", "updated_at"])

    return {
        "user_a": user_a,
        "user_b": user_b,
        "user_viewer": user_viewer,
        "org_a": org_a,
        "org_b": org_b,
        "seq_a": seq_a,
        "seq_b": seq_b,
    }


@pytest.mark.django_db
class TestDRFFoundation:
    def test_jwt_auth_flow(self, api_setup: dict[str, object]) -> None:
        client = APIClient()

        # 1. Obtain token pair
        resp = client.post(
            "/api/v1/auth/token/",
            {"email": "tenant_a_admin@example.com", "password": "Password123!"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "access" in data
        assert "refresh" in data
        access_token = data["access"]
        refresh_token = data["refresh"]

        # 2. Use bearer token on authenticated endpoint
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        org_a = api_setup["org_a"]
        resp_seq = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
        )
        assert resp_seq.status_code == status.HTTP_200_OK
        assert "results" in resp_seq.json()

        # 3. Refresh token
        client.credentials()  # Clear credentials
        resp_refresh = client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": refresh_token},
            format="json",
        )
        assert resp_refresh.status_code == status.HTTP_200_OK
        new_access = resp_refresh.json().get("access")
        assert new_access is not None

        # 4. Verify token
        resp_verify = client.post(
            "/api/v1/auth/token/verify/",
            {"token": new_access},
            format="json",
        )
        assert resp_verify.status_code == status.HTTP_200_OK

    def test_unauthenticated_request_envelope(self) -> None:
        client = APIClient()
        resp = client.get("/api/v1/core/sequences/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        data = resp.json()
        assert data["code"] == "not_authenticated"
        assert "message" in data
        assert "request_id" in data
        assert resp.headers.get("X-Request-ID") == data["request_id"]

    def test_request_id_middleware_propagation(self, api_setup: dict[str, object]) -> None:
        user_a = api_setup["user_a"]
        org_a = api_setup["org_a"]
        client = APIClient()
        client.force_authenticate(user=user_a)  # type: ignore[arg-type]

        # Custom incoming X-Request-ID
        custom_id = "test-custom-tracing-uuid-999"
        resp = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_REQUEST_ID=custom_id,
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
        )
        assert resp.status_code == status.HTTP_200_OK
        assert resp.headers.get("X-Request-ID") == custom_id

    def test_tenant_scoping_and_cross_tenant_isolation(self, api_setup: dict[str, object]) -> None:
        user_a = api_setup["user_a"]
        user_b = api_setup["user_b"]
        org_a = api_setup["org_a"]
        org_b = api_setup["org_b"]
        seq_a = api_setup["seq_a"]

        client_a = APIClient()
        client_a.force_authenticate(user=user_a)  # type: ignore[arg-type]

        # Org A lists sequences -> only sees seq_a
        resp_a = client_a.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
        )
        assert resp_a.status_code == status.HTTP_200_OK
        results_a = resp_a.json()["results"]
        prefixes_a = [r["prefix"] for r in results_a]
        assert "INV-" in prefixes_a
        assert "BETA-" not in prefixes_a

        # Org B user trying to retrieve Org A sequence by UUID -> 404 Not Found
        client_b = APIClient()
        client_b.force_authenticate(user=user_b)  # type: ignore[arg-type]
        resp_cross = client_b.get(
            f"/api/v1/core/sequences/{seq_a.public_id}/",  # type: ignore[attr-defined]
            HTTP_X_ORGANIZATION_ID=str(org_b.public_id),  # type: ignore[attr-defined]
        )
        assert resp_cross.status_code == status.HTTP_404_NOT_FOUND
        assert resp_cross.json()["code"] == "not_found"

    def test_permission_layer_1_feature_entitlement(self, api_setup: dict[str, object]) -> None:
        user_a = api_setup["user_a"]
        org_a = api_setup["org_a"]

        client = APIClient()
        client.force_authenticate(user=user_a)  # type: ignore[arg-type]

        # Disable 'settings' module entitlement for Org A
        set_feature_override(org_a.id, "settings", False)  # type: ignore[attr-defined]

        resp = client.get(
            "/api/v1/core/sequences/",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        data = resp.json()
        assert data["code"] == "plan_not_entitled"

    def test_permission_layer_2_role_permission(self, api_setup: dict[str, object]) -> None:
        user_viewer = api_setup["user_viewer"]
        org_a = api_setup["org_a"]

        client = APIClient()
        client.force_authenticate(user=user_viewer)  # type: ignore[arg-type]

        # Viewer role does NOT have 'settings.manage'
        resp = client.post(
            "/api/v1/core/sequences/",
            {"name": "Unauthorized Sequence", "prefix": "UNAUTH-"},
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
            format="json",
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        data = resp.json()
        assert data["code"] == "permission_denied"

    def test_idempotency_key_replay_and_conflict(self, api_setup: dict[str, object]) -> None:
        user_a = api_setup["user_a"]
        org_a = api_setup["org_a"]
        seq_a = api_setup["seq_a"]

        client = APIClient()
        client.force_authenticate(user=user_a)  # type: ignore[arg-type]

        url = f"/api/v1/core/sequences/{seq_a.public_id}/generate-next/"  # type: ignore[attr-defined]
        idempotency_key = "idemp-key-inv-001"

        # 1. First execution
        resp1 = client.post(
            url,
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        assert resp1.status_code == status.HTTP_200_OK
        data1 = resp1.json()
        assert data1["formatted_number"] == "INV-00001"
        assert "Idempotent-Replayed" not in resp1.headers

        # 2. Replay with identical key
        resp2 = client.post(
            url,
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        assert resp2.status_code == status.HTTP_200_OK
        assert resp2.json()["formatted_number"] == "INV-00001"
        assert resp2.headers.get("Idempotent-Replayed") == "true"

        # 3. Same key with different query param / payload -> 409 Conflict
        resp3 = client.post(
            f"{url}?altered_param=true",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )
        assert resp3.status_code == status.HTTP_409_CONFLICT
        assert resp3.json()["code"] == "idempotency_key_mismatch"

    def test_cursor_pagination(self, api_setup: dict[str, object]) -> None:
        user_a = api_setup["user_a"]
        org_a = api_setup["org_a"]

        with tenant_context(org_a):
            for i in range(5):
                NumberSequence.objects.create(
                    organization=org_a,  # type: ignore[arg-type]
                    name=f"Seq-{i}",
                    prefix=f"S{i}-",
                )

        client = APIClient()
        client.force_authenticate(user=user_a)  # type: ignore[arg-type]

        resp = client.get(
            "/api/v1/core/sequences/?page_size=2",
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["next"] is not None

    def test_validation_error_structure(self, api_setup: dict[str, object]) -> None:
        user_a = api_setup["user_a"]
        org_a = api_setup["org_a"]

        client = APIClient()
        client.force_authenticate(user=user_a)  # type: ignore[arg-type]

        # Missing required 'name' field
        resp = client.post(
            "/api/v1/core/sequences/",
            {"name": ""},
            HTTP_X_ORGANIZATION_ID=str(org_a.public_id),  # type: ignore[attr-defined]
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        data = resp.json()
        assert data["code"] == "validation_error"
        assert "name" in data["details"]
        assert data["request_id"] is not None
