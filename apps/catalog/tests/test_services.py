"""Unit tests for catalog domain services and business logic."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.accounts.models import User
from apps.catalog.exceptions import (
    DuplicateBarcodeError,
    DuplicateSkuError,
    InvalidPriceError,
    UnitConversionError,
)
from apps.catalog.models import (
    Category,
    Product,
    Unit,
)
from apps.catalog.services import (
    create_category,
    create_price_list,
    create_product,
    create_product_variant,
    create_unit,
    create_unit_conversion,
    export_products_csv,
    import_products_csv,
    resolve_product_price,
    set_price_list_item,
    update_category,
    update_product,
)
from apps.core.models import OutboxEvent
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Organization


@pytest.fixture
def catalog_org(db: None) -> Organization:
    return Organization.objects.create(name="Catalog Retail Co", slug="catalog-retail-co")


@pytest.fixture
def catalog_actor(db: None) -> User:
    return User.objects.create_user(email="catalog_mgr@example.com", password="Password123!")


@pytest.fixture
def base_unit(catalog_org: Organization) -> Unit:
    return create_unit(organization=catalog_org, name="Piece", code="pcs", precision=0)


@pytest.fixture
def base_category(catalog_org: Organization) -> Category:
    return create_category(organization=catalog_org, name="Electronics", slug="electronics")


@pytest.mark.django_db
def test_create_and_update_category(catalog_org: Organization) -> None:
    cat = create_category(
        organization=catalog_org,
        name="Laptops",
        slug="laptops",
        description="Portable computers",
    )
    assert cat.name == "Laptops"
    assert cat.slug == "laptops"
    assert cat.organization == catalog_org

    # Child category
    sub_cat = create_category(
        organization=catalog_org,
        name="Gaming Laptops",
        parent=cat,
    )
    assert sub_cat.parent == cat
    assert "laptops" in sub_cat.slug

    updated = update_category(category=sub_cat, name="Pro Gaming Laptops")
    assert updated.name == "Pro Gaming Laptops"


@pytest.mark.django_db
def test_unit_and_conversion(catalog_org: Organization, base_unit: Unit) -> None:
    box = create_unit(organization=catalog_org, name="Box", code="box", precision=0)
    conv = create_unit_conversion(
        organization=catalog_org,
        from_unit=box,
        to_unit=base_unit,
        factor=Decimal("12.000000"),
    )
    assert conv.factor == Decimal("12.000000")

    with pytest.raises(UnitConversionError, match="Conversion factor must be strictly positive"):
        create_unit_conversion(
            organization=catalog_org,
            from_unit=box,
            to_unit=base_unit,
            factor=Decimal("-5.000000"),
        )


@pytest.mark.django_db
def test_create_product_publishes_event(
    catalog_org: Organization,
    base_unit: Unit,
    base_category: Category,
    catalog_actor: User,
) -> None:
    product = create_product(
        organization=catalog_org,
        sku="LAPTOP-001",
        name="ThinkPad T14",
        unit=base_unit,
        category=base_category,
        cost_price=Decimal("800.0000"),
        selling_price=Decimal("1200.0000"),
        barcode="1234567890123",
        actor=catalog_actor,
    )

    assert product.sku == "LAPTOP-001"
    assert product.margin_percent == Decimal("50.0000")

    # Check outbox event
    event = OutboxEvent.objects.filter(
        organization_id=catalog_org.pk,
        event_type="catalog.product_created",
    ).first()
    assert event is not None
    assert event.payload["sku"] == "LAPTOP-001"
    assert event.payload["selling_price"] == "1200.0000"


@pytest.mark.django_db
def test_create_product_validations(
    catalog_org: Organization,
    base_unit: Unit,
    base_category: Category,
) -> None:
    create_product(
        organization=catalog_org,
        sku="PROD-UNIQ",
        name="Item Unique",
        unit=base_unit,
        barcode="BARCODE-111",
    )

    # Duplicate SKU in same org
    with pytest.raises(DuplicateSkuError):
        create_product(
            organization=catalog_org,
            sku="PROD-UNIQ",
            name="Another Item",
            unit=base_unit,
        )

    # Duplicate Barcode in same org
    with pytest.raises(DuplicateBarcodeError):
        create_product(
            organization=catalog_org,
            sku="PROD-OTHER",
            name="Another Item",
            unit=base_unit,
            barcode="BARCODE-111",
        )

    # Negative price
    with pytest.raises(InvalidPriceError):
        create_product(
            organization=catalog_org,
            sku="PROD-NEG",
            name="Bad Price",
            unit=base_unit,
            cost_price=Decimal("-10.0000"),
        )


@pytest.mark.django_db
def test_update_product_price_publishes_price_change_event(
    catalog_org: Organization,
    base_unit: Unit,
    catalog_actor: User,
) -> None:
    product = create_product(
        organization=catalog_org,
        sku="MOUSE-01",
        name="Wireless Mouse",
        unit=base_unit,
        cost_price=Decimal("15.0000"),
        selling_price=Decimal("30.0000"),
        actor=catalog_actor,
    )

    update_product(
        product=product,
        selling_price=Decimal("35.0000"),
        actor=catalog_actor,
    )

    event = OutboxEvent.objects.filter(
        organization_id=catalog_org.pk,
        event_type="catalog.price_changed",
    ).first()
    assert event is not None
    assert event.payload["old_price"] == "30.0000"
    assert event.payload["new_price"] == "35.0000"


@pytest.mark.django_db
def test_product_variants_and_overrides(
    catalog_org: Organization,
    base_unit: Unit,
    catalog_actor: User,
) -> None:
    product = create_product(
        organization=catalog_org,
        sku="TSHIRT-01",
        name="Cotton T-Shirt",
        unit=base_unit,
        cost_price=Decimal("10.0000"),
        selling_price=Decimal("20.0000"),
        actor=catalog_actor,
    )

    # Variant 1: standard price inherited
    var_s = create_product_variant(
        product=product,
        sku="TSHIRT-01-S",
        name="Small / Black",
        actor=catalog_actor,
    )
    assert var_s.effective_selling_price == Decimal("20.0000")
    assert var_s.effective_cost_price == Decimal("10.0000")

    # Variant 2: overridden price
    var_xl = create_product_variant(
        product=product,
        sku="TSHIRT-01-XL",
        name="XL / Black",
        selling_price_override=Decimal("25.0000"),
        cost_price_override=Decimal("12.0000"),
        actor=catalog_actor,
    )
    assert var_xl.effective_selling_price == Decimal("25.0000")
    assert var_xl.effective_cost_price == Decimal("12.0000")


@pytest.mark.django_db
def test_resolve_pricing_engine(
    catalog_org: Organization,
    base_unit: Unit,
    catalog_actor: User,
) -> None:
    product = create_product(
        organization=catalog_org,
        sku="KEYBOARD-01",
        name="Mechanical Keyboard",
        unit=base_unit,
        cost_price=Decimal("50.0000"),
        selling_price=Decimal("100.0000"),
        actor=catalog_actor,
    )

    # 1. Base price resolution without price list
    price_base = resolve_product_price(
        organization=catalog_org,
        product=product,
        quantity=Decimal("1.0000"),
    )
    assert price_base == Decimal("100.0000")

    # 2. Price List with quantity tiers
    pl_wholesale = create_price_list(
        organization=catalog_org,
        name="Wholesale Tier",
        currency="USD",
        actor=catalog_actor,
    )

    # Tier 1: min 5 units -> $90
    set_price_list_item(
        price_list=pl_wholesale,
        product=product,
        price=Decimal("90.0000"),
        min_quantity=Decimal("5.0000"),
    )

    # Tier 2: min 20 units -> $80
    set_price_list_item(
        price_list=pl_wholesale,
        product=product,
        price=Decimal("80.0000"),
        min_quantity=Decimal("20.0000"),
    )

    # Buying 2 units: under tier 1 -> returns base price 100
    p2 = resolve_product_price(
        organization=catalog_org,
        product=product,
        price_list=pl_wholesale,
        quantity=Decimal("2.0000"),
    )
    assert p2 == Decimal("100.0000")

    # Buying 10 units: meets tier 1 (min 5) -> returns 90
    p10 = resolve_product_price(
        organization=catalog_org,
        product=product,
        price_list=pl_wholesale,
        quantity=Decimal("10.0000"),
    )
    assert p10 == Decimal("90.0000")

    # Buying 50 units: meets tier 2 (min 20) -> returns 80
    p50 = resolve_product_price(
        organization=catalog_org,
        product=product,
        price_list=pl_wholesale,
        quantity=Decimal("50.0000"),
    )
    assert p50 == Decimal("80.0000")


@pytest.mark.django_db
def test_csv_export_and_import(
    catalog_org: Organization,
    base_unit: Unit,
    base_category: Category,
    catalog_actor: User,
) -> None:
    create_product(
        organization=catalog_org,
        sku="ITEM-A",
        name="Item Alpha",
        unit=base_unit,
        category=base_category,
        cost_price=Decimal("10.0000"),
        selling_price=Decimal("20.0000"),
        barcode="BAR-A",
    )

    # 1. Export CSV
    csv_str = export_products_csv(organization=catalog_org)
    assert "ITEM-A" in csv_str
    assert "Item Alpha" in csv_str
    assert "pcs" in csv_str

    # 2. Import CSV with a new item and an update to existing
    csv_input = (
        "sku,name,category,unit,type,cost_price,selling_price,barcode,reorder_level,reorder_quantity,is_active,description\n"
        "ITEM-A,Item Alpha Updated,Electronics,pcs,stock,12.00,24.00,BAR-A,5,10,true,Updated desc\n"
        "ITEM-B,Item Beta,Books,pcs,stock,5.00,15.00,BAR-B,0,0,true,Book item\n"
    )

    result = import_products_csv(
        organization=catalog_org,
        csv_content=csv_input,
        update_existing=True,
        actor=catalog_actor,
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 0

    with tenant_context(catalog_org):
        prod_a = Product.objects.get(sku="ITEM-A")
        assert prod_a.name == "Item Alpha Updated"
        assert prod_a.selling_price == Decimal("24.0000")

        prod_b = Product.objects.get(sku="ITEM-B")
        assert prod_b.name == "Item Beta"
        assert prod_b.selling_price == Decimal("15.0000")
        assert prod_b.category.name == "Books"
