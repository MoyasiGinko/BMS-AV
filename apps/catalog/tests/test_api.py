"""Integration tests for catalog DRF REST API endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.services import provision_billing_subscription, seed_default_plans
from apps.catalog.models import Category, Unit
from apps.catalog.services import (
    create_category,
    create_product,
    provision_catalog,
)
from apps.core.hooks import clear_provisioning_hooks, register_provisioning_hook
from apps.tenancy.models import Membership, Organization, Role
from apps.tenancy.services import provision_organization


@pytest.fixture
def catalog_api_setup(db: None) -> dict[str, object]:
    clear_provisioning_hooks()
    register_provisioning_hook(provision_billing_subscription)
    register_provisioning_hook(provision_catalog)
    seed_default_plans()

    admin_user = User.objects.create_user(email="api_admin@example.com", password="Password123!")
    org_a = provision_organization(name="API Corp A", slug="api-corp-a", owner=admin_user)

    # Viewer user with view-only role
    viewer_user = User.objects.create_user(email="api_viewer@example.com", password="Password123!")
    viewer_role = Role.all_tenants.filter(organization=org_a, name="Viewer").first()
    assert viewer_role is not None
    Membership.objects.create(
        organization=org_a,
        user=viewer_user,
        role=viewer_role,
        status=Membership.STATUS_ACTIVE,
    )

    # Other tenant for isolation checks
    other_user = User.objects.create_user(email="api_other@example.com", password="Password123!")
    org_b = provision_organization(name="API Corp B", slug="api-corp-b", owner=other_user)

    unit = Unit.all_tenants.filter(organization=org_a, code="pcs").first()
    assert unit is not None
    cat = create_category(organization=org_a, name="Electronics", slug="electronics")

    client = APIClient()
    client.force_authenticate(user=admin_user)

    return {
        "client": client,
        "admin_user": admin_user,
        "viewer_user": viewer_user,
        "other_user": other_user,
        "org_a": org_a,
        "org_b": org_b,
        "unit": unit,
        "category": cat,
    }


@pytest.mark.django_db
def test_category_api(catalog_api_setup: dict[str, object]) -> None:
    client: APIClient = catalog_api_setup["client"]  # type: ignore[assignment]
    org_a: Organization = catalog_api_setup["org_a"]  # type: ignore[assignment]
    viewer_user: User = catalog_api_setup["viewer_user"]  # type: ignore[assignment]

    # 1. List categories
    resp = client.get(
        "/api/v1/catalog/categories/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()["results"]) >= 1

    # 2. Create category
    resp_create = client.post(
        "/api/v1/catalog/categories/",
        {"name": "Appliances", "slug": "appliances"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_create.status_code == status.HTTP_201_CREATED
    assert resp_create.json()["name"] == "Appliances"

    # 3. Viewer user cannot create category (403 forbidden)
    viewer_client = APIClient()
    viewer_client.force_authenticate(user=viewer_user)
    resp_forbidden = viewer_client.post(
        "/api/v1/catalog/categories/",
        {"name": "Forbidden Category", "slug": "forbidden"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_forbidden.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_unit_api(catalog_api_setup: dict[str, object]) -> None:
    client: APIClient = catalog_api_setup["client"]  # type: ignore[assignment]
    org_a: Organization = catalog_api_setup["org_a"]  # type: ignore[assignment]

    # List
    resp = client.get(
        "/api/v1/catalog/units/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()["results"]) >= 1

    # Create
    resp_create = client.post(
        "/api/v1/catalog/units/",
        {"name": "Liter", "code": "L", "precision": 2},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_create.status_code == status.HTTP_201_CREATED
    assert resp_create.json()["code"] == "L"


@pytest.mark.django_db
def test_product_api_crud_and_filtering(catalog_api_setup: dict[str, object]) -> None:
    client: APIClient = catalog_api_setup["client"]  # type: ignore[assignment]
    org_a: Organization = catalog_api_setup["org_a"]  # type: ignore[assignment]
    unit: Unit = catalog_api_setup["unit"]  # type: ignore[assignment]
    cat: Category = catalog_api_setup["category"]  # type: ignore[assignment]

    # 1. Create Product
    product_data = {
        "sku": "DRF-PROD-01",
        "name": "DRF Sample Item",
        "unit_id": unit.pk,
        "category_id": cat.pk,
        "type": "stock",
        "cost_price": "50.0000",
        "selling_price": "100.0000",
        "barcode": "DRF-BAR-01",
    }
    resp = client.post(
        "/api/v1/catalog/products/",
        product_data,
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    created_id = resp.json()["id"]

    # 2. Retrieve Product
    resp_get = client.get(
        f"/api/v1/catalog/products/{created_id}/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_get.status_code == status.HTTP_200_OK
    assert resp_get.json()["sku"] == "DRF-PROD-01"

    # 3. Search and filtering
    resp_search = client.get(
        "/api/v1/catalog/products/?search=Sample",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_search.status_code == status.HTTP_200_OK
    assert len(resp_search.json()["results"]) == 1

    # 4. Partial update (PATCH)
    resp_patch = client.patch(
        f"/api/v1/catalog/products/{created_id}/",
        {"selling_price": "110.0000"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_patch.status_code == status.HTTP_200_OK
    assert Decimal(resp_patch.json()["selling_price"]) == Decimal("110.0000")


@pytest.mark.django_db
def test_price_list_api(catalog_api_setup: dict[str, object]) -> None:
    client: APIClient = catalog_api_setup["client"]  # type: ignore[assignment]
    org_a: Organization = catalog_api_setup["org_a"]  # type: ignore[assignment]

    # List
    resp = client.get(
        "/api/v1/catalog/price-lists/",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()["results"]) >= 1

    # Create
    resp_create = client.post(
        "/api/v1/catalog/price-lists/",
        {"name": "Online Tier", "currency": "USD"},
        format="json",
        HTTP_X_ORGANIZATION_ID=str(org_a.public_id),
    )
    assert resp_create.status_code == status.HTTP_201_CREATED
    assert resp_create.json()["name"] == "Online Tier"


@pytest.mark.django_db
def test_api_tenant_isolation(catalog_api_setup: dict[str, object]) -> None:
    org_a: Organization = catalog_api_setup["org_a"]  # type: ignore[assignment]
    org_b: Organization = catalog_api_setup["org_b"]  # type: ignore[assignment]
    other_user: User = catalog_api_setup["other_user"]  # type: ignore[assignment]
    unit: Unit = catalog_api_setup["unit"]  # type: ignore[assignment]

    prod_a = create_product(
        organization=org_a,
        sku="ISOLATION-01",
        name="Org A Only Item",
        unit=unit,
    )

    client_b = APIClient()
    client_b.force_authenticate(user=other_user)

    # 1. Org B listing products does not include Org A product
    resp = client_b.get(
        "/api/v1/catalog/products/",
        HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert len(resp.json()["results"]) == 0

    # 2. Org B direct retrieve of Org A product returns 404
    resp_404 = client_b.get(
        f"/api/v1/catalog/products/{prod_a.public_id}/",
        HTTP_X_ORGANIZATION_ID=str(org_b.public_id),
    )
    assert resp_404.status_code == status.HTTP_404_NOT_FOUND
