"""Services for managing product catalog, categories, pricing, and CSV operations."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from apps.catalog.events import ProductCreated, ProductPriceChanged, ProductUpdated
from apps.catalog.exceptions import (
    CatalogError,
    DuplicateBarcodeError,
    DuplicateSkuError,
    InvalidPriceError,
    UnitConversionError,
)
from apps.catalog.models import (
    Category,
    PriceList,
    PriceListItem,
    Product,
    ProductType,
    ProductVariant,
    Unit,
    UnitConversion,
)
from apps.core.events import publish
from apps.core.money import FOUR_PLACES
from apps.tenancy.models import Organization, TaxCode

DECIMAL_ZERO = Decimal("0.0000")


@transaction.atomic
def create_category(
    *,
    organization: Organization,
    name: str,
    slug: str = "",
    parent: Category | None = None,
    description: str = "",
    is_active: bool = True,
    sort_order: int = 0,
) -> Category:
    """Create a new product category."""
    cat_slug = slug.strip() or slugify(name)
    if not cat_slug:
        cat_slug = "category"

    # Ensure unique slug in organization
    base_slug = cat_slug
    counter = 1
    while Category.all_tenants.filter(organization=organization, slug=cat_slug).exists():
        cat_slug = f"{base_slug}-{counter}"
        counter += 1

    return Category.objects.create(
        organization=organization,
        name=name.strip(),
        slug=cat_slug,
        parent=parent,
        description=description.strip(),
        is_active=is_active,
        sort_order=sort_order,
    )


@transaction.atomic
def update_category(
    *,
    category: Category,
    name: str | None = None,
    slug: str | None = None,
    parent: Category | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> Category:
    """Update an existing category."""
    if name is not None:
        category.name = name.strip()
    if slug is not None and slug.strip():
        category.slug = slug.strip()
    if parent is not None:
        category.parent = parent
    if description is not None:
        category.description = description.strip()
    if is_active is not None:
        category.is_active = is_active
    if sort_order is not None:
        category.sort_order = sort_order

    category.save()
    return category


@transaction.atomic
def create_unit(
    *,
    organization: Organization,
    name: str,
    code: str,
    precision: int = 0,
    is_active: bool = True,
) -> Unit:
    """Create a unit of measure."""
    unit_code = code.strip().lower()
    if Unit.all_tenants.filter(organization=organization, code=unit_code).exists():
        raise CatalogError(f"Unit with code '{unit_code}' already exists.")

    return Unit.objects.create(
        organization=organization,
        name=name.strip(),
        code=unit_code,
        precision=precision,
        is_active=is_active,
    )


@transaction.atomic
def create_unit_conversion(
    *,
    organization: Organization,
    from_unit: Unit,
    to_unit: Unit,
    factor: Decimal | str | float,
) -> UnitConversion:
    """Create a unit conversion factor."""
    conv_factor = Decimal(str(factor))
    if conv_factor <= DECIMAL_ZERO:
        raise UnitConversionError("Conversion factor must be strictly positive.")

    conversion, _ = UnitConversion.all_tenants.update_or_create(
        organization=organization,
        from_unit=from_unit,
        to_unit=to_unit,
        defaults={"factor": conv_factor},
    )
    return conversion


@transaction.atomic
def create_product(
    *,
    organization: Organization,
    sku: str,
    name: str,
    unit: Unit,
    category: Category | None = None,
    type: str = ProductType.STOCK,
    cost_price: Decimal | str | int | float = DECIMAL_ZERO,
    selling_price: Decimal | str | int | float = DECIMAL_ZERO,
    barcode: str = "",
    tax_code: TaxCode | None = None,
    track_batch: bool = False,
    track_serial: bool = False,
    reorder_level: Decimal | str | int | float = DECIMAL_ZERO,
    reorder_quantity: Decimal | str | int | float = DECIMAL_ZERO,
    is_active: bool = True,
    description: str = "",
    actor: Any = None,
) -> Product:
    """Create a new commercial product item."""
    clean_sku = sku.strip()
    clean_barcode = barcode.strip()

    if Product.all_tenants.filter(organization=organization, sku__iexact=clean_sku).exists():
        raise DuplicateSkuError(f"Product with SKU '{clean_sku}' already exists.")

    if (
        clean_barcode
        and Product.all_tenants.filter(organization=organization, barcode=clean_barcode).exists()
    ):
        raise DuplicateBarcodeError(f"Barcode '{clean_barcode}' is already in use.")

    cost = Decimal(str(cost_price)).quantize(FOUR_PLACES)
    price = Decimal(str(selling_price)).quantize(FOUR_PLACES)

    if cost < DECIMAL_ZERO or price < DECIMAL_ZERO:
        raise InvalidPriceError("Cost and selling prices cannot be negative.")

    product = Product.objects.create(
        organization=organization,
        sku=clean_sku,
        barcode=clean_barcode,
        name=name.strip(),
        category=category,
        unit=unit,
        type=type,
        cost_price=cost,
        selling_price=price,
        tax_code=tax_code,
        track_batch=track_batch,
        track_serial=track_serial,
        reorder_level=Decimal(str(reorder_level)).quantize(FOUR_PLACES),
        reorder_quantity=Decimal(str(reorder_quantity)).quantize(FOUR_PLACES),
        is_active=is_active,
        description=description.strip(),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    publish(
        ProductCreated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            product_id=product.pk,
            sku=product.sku,
            name=product.name,
            selling_price=str(product.selling_price),
        )
    )

    return product


@transaction.atomic
def update_product(
    *,
    product: Product,
    actor: Any = None,
    **kwargs: Any,
) -> Product:
    """Update an existing product attributes."""
    old_price = product.selling_price
    price_changed = False

    for field, val in kwargs.items():
        if field == "sku" and val:
            new_sku = str(val).strip()
            if (
                Product.all_tenants.filter(organization=product.organization, sku__iexact=new_sku)
                .exclude(pk=product.pk)
                .exists()
            ):
                raise DuplicateSkuError(f"Product with SKU '{new_sku}' already exists.")
            product.sku = new_sku
        elif field == "barcode":
            new_bc = str(val or "").strip()
            if (
                new_bc
                and Product.all_tenants.filter(organization=product.organization, barcode=new_bc)
                .exclude(pk=product.pk)
                .exists()
            ):
                raise DuplicateBarcodeError(f"Barcode '{new_bc}' is already in use.")
            product.barcode = new_bc
        elif field in ("cost_price", "selling_price"):
            dec_val = Decimal(str(val)).quantize(FOUR_PLACES)
            if dec_val < DECIMAL_ZERO:
                raise InvalidPriceError(f"{field} cannot be negative.")
            setattr(product, field, dec_val)
            if field == "selling_price" and dec_val != old_price:
                price_changed = True
        elif hasattr(product, field):
            setattr(product, field, val)

    product.save()

    publish(
        ProductUpdated(
            organization_id=product.organization_id,
            actor_id=getattr(actor, "pk", None),
            product_id=product.pk,
            sku=product.sku,
        )
    )

    if price_changed:
        publish(
            ProductPriceChanged(
                organization_id=product.organization_id,
                actor_id=getattr(actor, "pk", None),
                product_id=product.pk,
                old_price=str(old_price),
                new_price=str(product.selling_price),
            )
        )

    return product


@transaction.atomic
def create_product_variant(
    *,
    product: Product,
    sku: str,
    name: str,
    attributes: dict[str, Any] | None = None,
    barcode: str = "",
    cost_price_override: Decimal | str | None = None,
    selling_price_override: Decimal | str | None = None,
    is_active: bool = True,
    actor: Any = None,
) -> ProductVariant:
    """Create a product variant."""
    clean_sku = sku.strip()
    clean_barcode = barcode.strip()

    if ProductVariant.all_tenants.filter(organization=product.organization, sku__iexact=clean_sku).exists():
        raise DuplicateSkuError(f"Variant with SKU '{clean_sku}' already exists.")

    cost_ovr = (
        Decimal(str(cost_price_override)).quantize(FOUR_PLACES) if cost_price_override is not None else None
    )
    sell_ovr = (
        Decimal(str(selling_price_override)).quantize(FOUR_PLACES)
        if selling_price_override is not None
        else None
    )

    return ProductVariant.objects.create(
        organization=product.organization,
        product=product,
        sku=clean_sku,
        barcode=clean_barcode,
        name=name.strip(),
        attributes=attributes or {},
        cost_price_override=cost_ovr,
        selling_price_override=sell_ovr,
        is_active=is_active,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def create_price_list(
    *,
    organization: Organization,
    name: str,
    currency: str = "USD",
    is_default: bool = False,
    is_active: bool = True,
    description: str = "",
    actor: Any = None,
) -> PriceList:
    """Create a price list."""
    clean_name = name.strip()
    if is_default:
        PriceList.all_tenants.filter(organization=organization, is_default=True).update(is_default=False)

    return PriceList.objects.create(
        organization=organization,
        name=clean_name,
        currency=currency.upper(),
        is_default=is_default,
        is_active=is_active,
        description=description.strip(),
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def set_price_list_item(
    *,
    price_list: PriceList,
    product: Product,
    price: Decimal | str | int | float,
    variant: ProductVariant | None = None,
    min_quantity: Decimal | str | int | float = Decimal("1.0000"),
) -> PriceListItem:
    """Assign or update a product price in a price list."""
    item_price = Decimal(str(price)).quantize(FOUR_PLACES)
    item_min_qty = Decimal(str(min_quantity)).quantize(FOUR_PLACES)

    if item_price < DECIMAL_ZERO:
        raise InvalidPriceError("Price cannot be negative.")

    item, _ = PriceListItem.all_tenants.update_or_create(
        organization=price_list.organization,
        price_list=price_list,
        product=product,
        variant=variant,
        min_quantity=item_min_qty,
        defaults={"price": item_price},
    )
    return item


def resolve_product_price(
    *,
    organization: Organization,
    product: Product,
    variant: ProductVariant | None = None,
    price_list: PriceList | None = None,
    quantity: Decimal | str | int | float = Decimal("1.0000"),
) -> Decimal:
    """Calculate the effective selling price for a product/variant.

    Resolution precedence:
    1. Matching rule in requested `price_list` with `min_quantity <= quantity`.
    2. Matching rule in organization default price list with `min_quantity <= quantity`.
    3. Variant's `effective_selling_price`.
    4. Product's `selling_price`.
    """
    qty = Decimal(str(quantity)).quantize(FOUR_PLACES)
    target_pl = price_list
    if target_pl is None:
        target_pl = PriceList.all_tenants.filter(
            organization=organization, is_default=True, is_active=True
        ).first()

    if target_pl is not None:
        rule_qs = PriceListItem.all_tenants.filter(
            organization=organization,
            price_list=target_pl,
            product=product,
            min_quantity__lte=qty,
        )
        if variant is not None:
            rule_variant = rule_qs.filter(variant=variant).order_by("-min_quantity").first()
            if rule_variant is not None:
                return rule_variant.price

        rule_product = rule_qs.filter(variant__isnull=True).order_by("-min_quantity").first()
        if rule_product is not None:
            return rule_product.price

    if variant is not None:
        return variant.effective_selling_price

    return product.selling_price


# ---------------------------------------------------------------------------
# CSV Import & Export
# ---------------------------------------------------------------------------

CSV_HEADERS = [
    "sku",
    "barcode",
    "name",
    "category",
    "unit",
    "type",
    "cost_price",
    "selling_price",
    "tax_code",
    "reorder_level",
    "reorder_quantity",
    "is_active",
    "description",
]


def export_products_csv(*, organization: Organization) -> str:
    """Export all products in an organization as a CSV string."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS)
    writer.writeheader()

    products = (
        Product.all_tenants.filter(organization=organization)
        .select_related("category", "unit", "tax_code")
        .order_by("name")
    )

    for p in products:
        writer.writerow(
            {
                "sku": p.sku,
                "barcode": p.barcode,
                "name": p.name,
                "category": p.category.name if p.category else "",
                "unit": p.unit.code,
                "type": p.type,
                "cost_price": str(p.cost_price),
                "selling_price": str(p.selling_price),
                "tax_code": p.tax_code.code if p.tax_code else "",
                "reorder_level": str(p.reorder_level),
                "reorder_quantity": str(p.reorder_quantity),
                "is_active": "true" if p.is_active else "false",
                "description": p.description,
            }
        )

    return output.getvalue()


def _process_csv_row(
    organization: Organization,
    row: dict[str, Any],
    update_existing: bool,
    actor: Any,
) -> str:
    sku = (row.get("sku") or "").strip()
    name = (row.get("name") or "").strip()
    if not sku or not name:
        return "missing"

    unit_code = (row.get("unit") or "pcs").strip().lower()
    unit = Unit.all_tenants.filter(organization=organization, code=unit_code).first()
    if unit is None:
        unit = create_unit(organization=organization, name=unit_code.capitalize(), code=unit_code)

    cat_name = (row.get("category") or "").strip()
    category = None
    if cat_name:
        category = Category.all_tenants.filter(organization=organization, name__iexact=cat_name).first()
        if category is None:
            category = create_category(organization=organization, name=cat_name)

    tax_code_str = (row.get("tax_code") or "").strip()
    tax_code = None
    if tax_code_str:
        tax_code = TaxCode.all_tenants.filter(organization=organization, code__iexact=tax_code_str).first()

    cost_val = Decimal(str(row.get("cost_price") or "0.0000")).quantize(FOUR_PLACES)
    sell_val = Decimal(str(row.get("selling_price") or "0.0000")).quantize(FOUR_PLACES)
    reorder_lvl = Decimal(str(row.get("reorder_level") or "0.0000")).quantize(FOUR_PLACES)
    reorder_qty = Decimal(str(row.get("reorder_quantity") or "0.0000")).quantize(FOUR_PLACES)
    p_type = (row.get("type") or ProductType.STOCK).strip().lower()
    if p_type not in ProductType.values:
        p_type = ProductType.STOCK

    is_act = row.get("is_active", "true").strip().lower() in ("true", "1", "yes")
    barcode = (row.get("barcode") or "").strip()
    description = (row.get("description") or "").strip()

    existing = Product.all_tenants.filter(organization=organization, sku__iexact=sku).first()
    if existing:
        if not update_existing:
            return "skipped"
        existing.name = name
        existing.category = category
        existing.unit = unit
        existing.type = p_type
        existing.cost_price = cost_val
        existing.selling_price = sell_val
        existing.barcode = barcode
        existing.tax_code = tax_code
        existing.reorder_level = reorder_lvl
        existing.reorder_quantity = reorder_qty
        existing.is_active = is_act
        existing.description = description
        existing.save()
        return "updated"

    Product.objects.create(
        organization=organization,
        sku=sku,
        barcode=barcode,
        name=name,
        category=category,
        unit=unit,
        type=p_type,
        cost_price=cost_val,
        selling_price=sell_val,
        tax_code=tax_code,
        reorder_level=reorder_lvl,
        reorder_quantity=reorder_qty,
        is_active=is_act,
        description=description,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return "created"


@transaction.atomic
def import_products_csv(
    *,
    organization: Organization,
    csv_content: str,
    update_existing: bool = True,
    actor: Any = None,
) -> dict[str, Any]:
    """Import products from CSV string with automatic unit/category resolution."""
    reader = csv.DictReader(io.StringIO(csv_content))
    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors: list[str] = []

    for row_idx, row in enumerate(reader, start=2):
        row_status = _process_csv_row(organization, row, update_existing, actor)
        if row_status == "missing":
            errors.append(f"Row {row_idx}: Missing required SKU or Name.")
            skipped_count += 1
        elif row_status == "created":
            created_count += 1
        elif row_status == "updated":
            updated_count += 1
        else:
            skipped_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": errors,
    }


def provision_catalog(ctx: Any) -> None:
    """Tenant provisioning hook for catalog units and default price list."""
    org = ctx.organization

    # 1. Seed standard units
    standard_units = [
        ("Piece", "pcs", 0),
        ("Box", "box", 0),
        ("Kilogram", "kg", 2),
        ("Meter", "m", 2),
        ("Hour", "hr", 1),
    ]
    created_units: dict[str, Unit] = {}
    for name, code, prec in standard_units:
        unit, _ = Unit.all_tenants.get_or_create(
            organization=org,
            code=code,
            defaults={"name": name, "precision": prec},
        )
        created_units[code] = unit

    # 2. Seed standard conversion (1 Box = 12 Pieces)
    if "box" in created_units and "pcs" in created_units:
        UnitConversion.all_tenants.get_or_create(
            organization=org,
            from_unit=created_units["box"],
            to_unit=created_units["pcs"],
            defaults={"factor": Decimal("12.000000")},
        )

    # 3. Seed default price list
    PriceList.all_tenants.get_or_create(
        organization=org,
        name="Standard Retail",
        defaults={
            "currency": org.base_currency or "USD",
            "is_default": True,
            "description": "Default standard retail price list",
        },
    )
