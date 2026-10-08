"""Tenant isolation tests for catalog models and selectors."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.catalog.models import Category, PriceList, Product, Unit
from apps.catalog.selectors import (
    get_product_by_barcode,
    get_product_by_id,
    get_product_by_sku,
    list_products,
)
from apps.catalog.services import (
    create_category,
    create_price_list,
    create_product,
    create_unit,
    export_products_csv,
)
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization


@pytest.fixture
def org_alpha(db: None) -> Organization:
    return Organization.objects.create(name="Alpha Corp", slug="alpha-corp")


@pytest.fixture
def org_beta(db: None) -> Organization:
    return Organization.objects.create(name="Beta Corp", slug="beta-corp")


@pytest.mark.django_db
def test_cross_tenant_isolation(org_alpha: Organization, org_beta: Organization) -> None:
    # 1. Setup in Org Alpha
    unit_a = create_unit(organization=org_alpha, name="Piece", code="pcs")
    cat_a = create_category(organization=org_alpha, name="Hardware", slug="hardware")
    prod_a = create_product(
        organization=org_alpha,
        sku="SHARED-SKU-01",
        name="Alpha Tool",
        unit=unit_a,
        category=cat_a,
        cost_price=Decimal("10.0000"),
        selling_price=Decimal("20.0000"),
        barcode="ALPHA-BARCODE-01",
    )
    pl_a = create_price_list(organization=org_alpha, name="Alpha Special List")

    # 2. Org Beta cannot see Org Alpha items via TenantModel manager
    with tenant_context(org_beta):
        assert Product.objects.filter(pk=prod_a.pk).count() == 0
        assert Category.objects.filter(pk=cat_a.pk).count() == 0
        assert PriceList.objects.filter(pk=pl_a.pk).count() == 0
        assert Unit.objects.filter(pk=unit_a.pk).count() == 0

    # 3. Org Beta selectors return None
    assert get_product_by_id(organization_id=org_beta.pk, product_id=prod_a.pk) is None
    assert get_product_by_sku(organization_id=org_beta.pk, sku="SHARED-SKU-01") is None
    assert get_product_by_barcode(organization_id=org_beta.pk, barcode="ALPHA-BARCODE-01") is None
    assert list_products(organization_id=org_beta.pk).count() == 0

    # 4. Same SKU allowed across different organizations without uniqueness collision
    unit_b = create_unit(organization=org_beta, name="Piece", code="pcs")
    prod_b = create_product(
        organization=org_beta,
        sku="SHARED-SKU-01",
        name="Beta Distinct Tool",
        unit=unit_b,
        cost_price=Decimal("15.0000"),
        selling_price=Decimal("30.0000"),
    )
    assert prod_b.pk != prod_a.pk
    assert prod_b.sku == prod_a.sku

    # 5. CSV export for Org Beta does not leak Org Alpha
    csv_beta = export_products_csv(organization=org_beta)
    assert "Alpha Tool" not in csv_beta
    assert "Beta Distinct Tool" in csv_beta
