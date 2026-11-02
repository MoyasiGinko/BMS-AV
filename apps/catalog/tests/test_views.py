"""Integration tests for catalog web screens, HTMX partials, and CSV views."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import (
    Category,
    PriceList,
    PriceListItem,
    Product,
    ProductVariant,
    Unit,
)
from apps.catalog.services import (
    create_category,
    create_product,
    create_unit,
)
from apps.tenancy.models import Membership, Organization, Role


@pytest.fixture
def catalog_setup(db: None) -> dict[str, object]:
    user = User.objects.create_user(email="catalog_admin@example.com", password="Password123!")
    org = Organization.objects.create(name="View Test Org", slug="view-test-org")

    # Give user an Owner role with full permissions
    role = Role.objects.create(
        organization=org,
        name="Owner",
        permissions=["catalog.view", "catalog.manage"],
    )
    Membership.objects.create(
        organization=org,
        user=user,
        role=role,
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    client = Client()
    client.force_login(user)

    unit = create_unit(organization=org, name="Piece", code="pcs")
    cat = create_category(organization=org, name="Hardware", slug="hardware")

    return {
        "client": client,
        "user": user,
        "org": org,
        "unit": unit,
        "category": cat,
        "headers": {"HTTP_X_ORGANIZATION_ID": str(org.public_id)},
    }


@pytest.mark.django_db
def test_product_list_and_htmx_partial(catalog_setup: dict[str, object]) -> None:
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    create_product(
        organization=org,
        sku="SCREEN-PROD-01",
        name="Sample Screen Item",
        unit=unit,
        selling_price=Decimal("49.9900"),
    )

    # 1. Full page request
    res = client.get(reverse("catalog:product_list"), **headers)
    assert res.status_code == 200
    assert "Sample Screen Item" in res.content.decode()
    assert "Products & Catalog" in res.content.decode()

    # 2. HTMX partial request
    htmx_headers = {**headers, "HTTP_HX_REQUEST": "true"}
    res_htmx = client.get(
        reverse("catalog:product_list") + "?q=Screen",
        **htmx_headers,
    )
    assert res_htmx.status_code == 200
    assert "product-table-container" in res_htmx.content.decode()
    assert "SCREEN-PROD-01" in res_htmx.content.decode()


@pytest.mark.django_db
def test_product_create_and_detail_and_edit_views(catalog_setup: dict[str, object]) -> None:
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    cat: Category = catalog_setup["category"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    # 1. GET product create
    res_get = client.get(reverse("catalog:product_create"), **headers)
    assert res_get.status_code == 200

    # 2. POST product create
    post_data = {
        "sku": "NEW-PRODUCT-01",
        "name": "Brand New Gadget",
        "unit_id": unit.pk,
        "category_id": cat.pk,
        "type": "stock",
        "cost_price": "25.0000",
        "selling_price": "50.0000",
        "barcode": "1122334455",
        "reorder_level": "5",
        "reorder_quantity": "20",
        "is_active": "on",
    }
    res_post = client.post(reverse("catalog:product_create"), post_data, **headers)
    assert res_post.status_code == 302

    created_prod = Product.all_tenants.get(organization=org, sku="NEW-PRODUCT-01")
    assert created_prod.name == "Brand New Gadget"

    # 3. GET product detail
    res_detail = client.get(reverse("catalog:product_detail", kwargs={"pk": created_prod.pk}), **headers)
    assert res_detail.status_code == 200
    assert "Brand New Gadget" in res_detail.content.decode()

    # 4. POST product edit
    edit_data = {
        **post_data,
        "name": "Updated Gadget Name",
        "selling_price": "55.0000",
    }
    res_edit = client.post(
        reverse("catalog:product_edit", kwargs={"pk": created_prod.pk}),
        edit_data,
        **headers,
    )
    assert res_edit.status_code == 302
    created_prod.refresh_from_db()
    assert created_prod.name == "Updated Gadget Name"
    assert created_prod.selling_price == Decimal("55.0000")


@pytest.mark.django_db
def test_product_variant_create_view(catalog_setup: dict[str, object]) -> None:
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    prod = create_product(
        organization=org,
        sku="TSHIRT-BASE",
        name="Cotton Shirt",
        unit=unit,
        selling_price=Decimal("20.0000"),
    )

    variant_data = {
        "sku": "TSHIRT-BASE-M",
        "name": "Medium",
        "barcode": "999888777",
        "selling_price_override": "22.0000",
        "cost_price_override": "11.0000",
        "is_active": "on",
    }
    res = client.post(
        reverse("catalog:product_variant_create", kwargs={"pk": prod.pk}),
        variant_data,
        **headers,
    )
    assert res.status_code == 302
    assert ProductVariant.all_tenants.filter(product=prod, sku="TSHIRT-BASE-M").exists()


@pytest.mark.django_db
def test_category_and_unit_views(catalog_setup: dict[str, object]) -> None:
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    # Category list & create
    res_cat_get = client.get(reverse("catalog:category_list"), **headers)
    assert res_cat_get.status_code == 200

    res_cat_post = client.post(
        reverse("catalog:category_list"),
        {"name": "Footwear", "slug": "footwear", "is_active": "on"},
        **headers,
    )
    assert res_cat_post.status_code == 302
    assert Category.all_tenants.filter(organization=org, slug="footwear").exists()

    # Unit list & create
    res_unit_get = client.get(reverse("catalog:unit_list"), **headers)
    assert res_unit_get.status_code == 200

    res_unit_post = client.post(
        reverse("catalog:unit_list"),
        {"name": "Meter", "code": "m", "precision": 2},
        **headers,
    )
    assert res_unit_post.status_code == 302
    assert Unit.all_tenants.filter(organization=org, code="m").exists()


@pytest.mark.django_db
def test_pricelist_views(catalog_setup: dict[str, object]) -> None:
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    prod = create_product(
        organization=org,
        sku="PHONE-01",
        name="Smart Phone",
        unit=unit,
        selling_price=Decimal("500.0000"),
    )

    # 1. Create Price List
    res_pl_post = client.post(
        reverse("catalog:pricelist_list"),
        {"name": "VIP Club", "currency": "USD", "is_default": "on"},
        **headers,
    )
    assert res_pl_post.status_code == 302

    pl = PriceList.all_tenants.get(organization=org, name="VIP Club")

    # 2. View detail
    res_detail = client.get(reverse("catalog:pricelist_detail", kwargs={"pk": pl.pk}), **headers)
    assert res_detail.status_code == 200

    # 3. Add item override
    item_post = {
        "product_id": prod.pk,
        "price": "450.0000",
        "min_quantity": "1.0000",
    }
    res_item_post = client.post(
        reverse("catalog:pricelist_detail", kwargs={"pk": pl.pk}),
        item_post,
        **headers,
    )
    assert res_item_post.status_code == 302
    assert PriceListItem.all_tenants.filter(price_list=pl, product=prod, price=Decimal("450.0000")).exists()


@pytest.mark.django_db
def test_export_and_import_csv_views(catalog_setup: dict[str, object]) -> None:
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    create_product(
        organization=org,
        sku="EXP-01",
        name="Exportable Product",
        unit=unit,
        selling_price=Decimal("15.0000"),
    )

    # Export
    res_exp = client.get(reverse("catalog:export_csv"), **headers)
    assert res_exp.status_code == 200
    assert res_exp["Content-Type"] == "text/csv"
    assert "EXP-01" in res_exp.content.decode()

    # Import
    csv_body = (
        "sku,name,category,unit,type,cost_price,selling_price,barcode,reorder_level,reorder_quantity,is_active,description\n"
        "IMP-01,Imported Item,,pcs,stock,5.00,10.00,IMPBAR,0,0,true,Test CSV import\n"
    )
    csv_file = SimpleUploadedFile("products.csv", csv_body.encode("utf-8"), content_type="text/csv")

    res_imp = client.post(
        reverse("catalog:import_csv"),
        {"csv_file": csv_file, "update_existing": "on"},
        **headers,
    )
    assert res_imp.status_code == 302
    assert Product.all_tenants.filter(organization=org, sku="IMP-01").exists()


@pytest.mark.django_db
def test_product_labels_view_accessible(catalog_setup: dict[str, object]) -> None:
    """Test product label printing and designer screen loads with active products."""
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    create_product(
        organization=org,
        sku="LBL-01",
        name="Label Test Product",
        unit=unit,
        selling_price=Decimal("25.5000"),
        barcode="8901234567890",
    )

    # Test both registered URL patterns
    res1 = client.get(reverse("catalog:product_labels"), **headers)
    assert res1.status_code == 200
    assert "products_json" in res1.context
    assert "active_tab" in res1.context
    assert res1.context["active_tab"] == "labels"
    assert "LBL-01" in res1.context["products_json"]
    assert "8901234567890" in res1.context["products_json"]
    assert "Print Labels" in res1.content.decode()

    res2 = client.get(reverse("catalog:label_print"), **headers)
    assert res2.status_code == 200


@pytest.mark.django_db
def test_product_labels_view_preselected_product(catalog_setup: dict[str, object]) -> None:
    """Test navigating to labels screen with a preselected product."""
    client: Client = catalog_setup["client"]  # type: ignore[assignment]
    org: Organization = catalog_setup["org"]  # type: ignore[assignment]
    unit: Unit = catalog_setup["unit"]  # type: ignore[assignment]
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    prod = create_product(
        organization=org,
        sku="PRE-01",
        name="Preselected Item",
        unit=unit,
        selling_price=Decimal("12.0000"),
    )

    url = f"{reverse('catalog:product_labels')}?product_id={prod.pk}"
    res = client.get(url, **headers)
    assert res.status_code == 200
    assert res.context["preselected_product_id"] == prod.pk


@pytest.mark.django_db
def test_product_labels_view_permission_denied(catalog_setup: dict[str, object]) -> None:
    """Test unauthorized access to label printing is blocked."""
    headers: dict[str, str] = catalog_setup["headers"]  # type: ignore[assignment]

    unprivileged_user = User.objects.create_user(email="no_perm_user@example.com", password="Password123!")
    client = Client()
    client.force_login(unprivileged_user)

    res = client.get(reverse("catalog:product_labels"), **headers)
    assert res.status_code == 403
