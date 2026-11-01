"""Selectors for reading product catalog entities."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.catalog.models import (
    Category,
    PriceList,
    PriceListItem,
    Product,
    ProductVariant,
    Unit,
)


def get_product_by_id(*, organization_id: int, product_id: int) -> Product | None:
    """Retrieve product with relations pre-fetched."""
    return (
        Product.all_tenants.filter(organization_id=organization_id, pk=product_id)
        .select_related("category", "unit", "tax_code")
        .prefetch_related("variants", "images")
        .first()
    )


def get_product_by_sku(*, organization_id: int, sku: str) -> Product | None:
    """Retrieve product by exact SKU."""
    return (
        Product.all_tenants.filter(organization_id=organization_id, sku__iexact=sku.strip())
        .select_related("category", "unit", "tax_code")
        .first()
    )


def get_product_by_barcode(*, organization_id: int, barcode: str) -> Product | None:
    """Retrieve product or variant by exact barcode scan."""
    clean_bc = barcode.strip()
    if not clean_bc:
        return None

    # Check main product
    prod = (
        Product.all_tenants.filter(organization_id=organization_id, barcode=clean_bc)
        .select_related("category", "unit", "tax_code")
        .first()
    )
    if prod is not None:
        return prod

    # Check variant
    variant = (
        ProductVariant.all_tenants.filter(organization_id=organization_id, barcode=clean_bc)
        .select_related("product__category", "product__unit", "product__tax_code")
        .first()
    )
    return variant.product if variant else None


def list_products(
    *,
    organization_id: int,
    search: str = "",
    category_id: int | None = None,
    is_active: bool | None = None,
    product_type: str | None = None,
) -> QuerySet[Product]:
    """Search and filter product catalog."""
    qs = (
        Product.all_tenants.filter(organization_id=organization_id)
        .select_related("category", "unit", "tax_code")
        .prefetch_related("variants", "images")
    )

    if search.strip():
        term = search.strip()
        qs = qs.filter(
            Q(name__icontains=term)
            | Q(sku__icontains=term)
            | Q(barcode__icontains=term)
            | Q(description__icontains=term)
        )

    if category_id:
        qs = qs.filter(category_id=category_id)

    if is_active is not None:
        qs = qs.filter(is_active=is_active)

    if product_type:
        qs = qs.filter(type=product_type)

    return qs.order_by("name")


def list_categories(*, organization_id: int, parent_id: int | None = None) -> QuerySet[Category]:
    """Retrieve categories tree ordered by sort_order and name."""
    qs = Category.all_tenants.filter(organization_id=organization_id).select_related("parent")
    if parent_id is not None:
        qs = qs.filter(parent_id=parent_id)
    return qs.order_by("sort_order", "name")


def list_units(*, organization_id: int) -> QuerySet[Unit]:
    """Retrieve all units of measure for an organization."""
    return Unit.all_tenants.filter(organization_id=organization_id).order_by("name")


def list_price_lists(*, organization_id: int) -> QuerySet[PriceList]:
    """Retrieve all price lists for an organization."""
    return PriceList.all_tenants.filter(organization_id=organization_id).order_by("-is_default", "name")


def get_price_list_items(*, organization_id: int, price_list_id: int) -> QuerySet[PriceListItem]:
    """Retrieve all items in a price list with product details."""
    return (
        PriceListItem.all_tenants.filter(organization_id=organization_id, price_list_id=price_list_id)
        .select_related("product", "variant")
        .order_by("product__name", "min_quantity")
    )
