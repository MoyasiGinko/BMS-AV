"""Views for Product Catalog screens, HTMX partials, and CSV import/export."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from apps.catalog.exceptions import CatalogError
from apps.catalog.forms import (
    CategoryForm,
    CsvImportForm,
    PriceListForm,
    PriceListItemForm,
    ProductForm,
    ProductVariantForm,
    UnitForm,
)
from apps.catalog.models import (
    Category,
    PriceList,
    Product,
    ProductType,
    Unit,
)
from apps.catalog.selectors import (
    get_price_list_items,
    get_product_by_id,
    list_categories,
    list_price_lists,
    list_products,
    list_units,
)
from apps.catalog.services import (
    create_category,
    create_price_list,
    create_product,
    create_product_variant,
    create_unit,
    export_products_csv,
    import_products_csv,
    set_price_list_item,
    update_product,
)
from apps.core.permissions import has_permission
from apps.tenancy.models import Organization, TaxCode


def _get_active_org(request: HttpRequest) -> Organization:
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


def _check_perm(request: HttpRequest, code: str, org: Organization) -> None:
    if not has_permission(user=request.user, permission_code=code, organization=org):
        raise PermissionDenied(_("You do not have permission to access this resource."))


@login_required
def product_list_view(request: HttpRequest) -> HttpResponse:
    """Product catalog directory with search, filtering, and HTMX pagination."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    search = request.GET.get("q", "")
    category_id = request.GET.get("category")
    cat_id = int(category_id) if category_id and category_id.isdigit() else None
    product_type = request.GET.get("type", "")
    is_active_param = request.GET.get("status", "")
    is_active = True if is_active_param == "active" else (False if is_active_param == "inactive" else None)

    products_qs = list_products(
        organization_id=org.pk,
        search=search,
        category_id=cat_id,
        product_type=product_type if product_type in ProductType.values else None,
        is_active=is_active,
    )

    paginator = Paginator(products_qs, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    categories = list_categories(organization_id=org.pk)
    all_prods = Product.all_tenants.filter(organization=org)
    metrics = {
        "total_products": all_prods.count(),
        "active_products": all_prods.filter(is_active=True).count(),
        "total_categories": len(categories),
        "discounted_products": all_prods.filter(discount_percent__gt=0).count(),
    }

    context = {
        "metrics": metrics,
        "page_obj": page_obj,
        "products": page_obj.object_list,
        "categories": categories,
        "search": search,
        "selected_category": cat_id,
        "selected_type": product_type,
        "selected_status": is_active_param,
        "total_count": paginator.count,
        "import_form": CsvImportForm(),
    }

    if request.headers.get("HX-Request") and not request.headers.get("HX-Boosted"):
        return render(request, "catalog/partials/product_table.html", context)

    return render(request, "catalog/product_list.html", context)


@login_required
def product_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new product."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.manage", org)

    if request.method == "POST":
        form = ProductForm(request.POST, organization_id=org.pk)
        if form.is_valid():
            data = form.cleaned_data
            unit = get_object_or_404(Unit.all_tenants, organization=org, pk=data["unit_id"])
            category = None
            if data.get("category_id"):
                category = Category.all_tenants.filter(organization=org, pk=data["category_id"]).first()
            tax_code = None
            if data.get("tax_code_id"):
                tax_code = TaxCode.all_tenants.filter(organization=org, pk=data["tax_code_id"]).first()

            try:
                product = create_product(
                    organization=org,
                    sku=data["sku"],
                    name=data["name"],
                    unit=unit,
                    category=category,
                    type=data["type"],
                    cost_price=data["cost_price"],
                    selling_price=data["selling_price"],
                    discount_percent=data.get("discount_percent") or Decimal("0.00"),
                    barcode=data.get("barcode", ""),
                    tax_code=tax_code,
                    track_batch=data.get("track_batch", False),
                    track_serial=data.get("track_serial", False),
                    reorder_level=data.get("reorder_level", 0),
                    reorder_quantity=data.get("reorder_quantity", 0),
                    is_active=data.get("is_active", True),
                    description=data.get("description", ""),
                    actor=request.user,
                )
                messages.success(
                    request, _("Product '%(name)s' created successfully.") % {"name": product.name}
                )
                return redirect("catalog:product_detail", pk=product.pk)
            except CatalogError as err:
                messages.error(request, str(err))
    else:
        form = ProductForm(organization_id=org.pk)

    return render(request, "catalog/product_form.html", {"form": form, "is_new": True})


@login_required
def product_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View product details, variants, and price list items."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    product = get_product_by_id(organization_id=org.pk, product_id=pk)
    if product is None:
        raise PermissionDenied(_("Product not found."))

    variants = product.variants.all()
    variant_form = ProductVariantForm()

    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "variants": variants,
            "variant_form": variant_form,
        },
    )


@login_required
def product_edit_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit existing product details."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.manage", org)

    product = get_product_by_id(organization_id=org.pk, product_id=pk)
    if product is None:
        raise PermissionDenied(_("Product not found."))

    if request.method == "POST":
        form = ProductForm(request.POST, organization_id=org.pk)
        if form.is_valid():
            data = form.cleaned_data
            unit = get_object_or_404(Unit.all_tenants, organization=org, pk=data["unit_id"])
            category = None
            if data.get("category_id"):
                category = Category.all_tenants.filter(organization=org, pk=data["category_id"]).first()
            tax_code = None
            if data.get("tax_code_id"):
                tax_code = TaxCode.all_tenants.filter(organization=org, pk=data["tax_code_id"]).first()

            try:
                update_product(
                    product=product,
                    sku=data["sku"],
                    name=data["name"],
                    unit=unit,
                    category=category,
                    type=data["type"],
                    cost_price=data["cost_price"],
                    selling_price=data["selling_price"],
                    discount_percent=data.get("discount_percent") or Decimal("0.00"),
                    barcode=data.get("barcode", ""),
                    tax_code=tax_code,
                    track_batch=data.get("track_batch", False),
                    track_serial=data.get("track_serial", False),
                    reorder_level=data.get("reorder_level", 0),
                    reorder_quantity=data.get("reorder_quantity", 0),
                    is_active=data.get("is_active", True),
                    description=data.get("description", ""),
                    actor=request.user,
                )
                messages.success(request, _("Product updated successfully."))
                return redirect("catalog:product_detail", pk=product.pk)
            except CatalogError as err:
                messages.error(request, str(err))
    else:
        initial = {
            "sku": product.sku,
            "name": product.name,
            "barcode": product.barcode,
            "category_id": product.category_id,
            "unit_id": product.unit_id,
            "type": product.type,
            "cost_price": product.cost_price,
            "selling_price": product.selling_price,
            "discount_percent": product.discount_percent,
            "tax_code_id": product.tax_code_id,
            "reorder_level": product.reorder_level,
            "reorder_quantity": product.reorder_quantity,
            "is_active": product.is_active,
            "track_batch": product.track_batch,
            "track_serial": product.track_serial,
            "description": product.description,
        }
        form = ProductForm(initial=initial, organization_id=org.pk)

    return render(
        request,
        "catalog/product_form.html",
        {"form": form, "product": product, "is_new": False},
    )


@login_required
@require_POST
def product_variant_create_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Add a variant to a product."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.manage", org)

    product = get_object_or_404(Product.all_tenants, organization=org, pk=pk)
    form = ProductVariantForm(request.POST)

    if form.is_valid():
        data = form.cleaned_data
        try:
            create_product_variant(
                product=product,
                sku=data["sku"],
                name=data["name"],
                barcode=data.get("barcode", ""),
                cost_price_override=data.get("cost_price_override"),
                selling_price_override=data.get("selling_price_override"),
                is_active=data.get("is_active", True),
                actor=request.user,
            )
            messages.success(request, _("Variant added successfully."))
        except CatalogError as err:
            messages.error(request, str(err))
    else:
        messages.error(request, _("Please provide valid variant details."))

    return redirect("catalog:product_detail", pk=product.pk)


@login_required
def category_list_view(request: HttpRequest) -> HttpResponse:
    """Manage categories."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    if request.method == "POST":
        _check_perm(request, "catalog.manage", org)
        form = CategoryForm(request.POST, organization_id=org.pk)
        if form.is_valid():
            data = form.cleaned_data
            parent = None
            if data.get("parent_id"):
                parent = Category.all_tenants.filter(organization=org, pk=data["parent_id"]).first()
            create_category(
                organization=org,
                name=data["name"],
                slug=data.get("slug", ""),
                parent=parent,
                description=data.get("description", ""),
                is_active=data.get("is_active", True),
            )
            messages.success(request, _("Category created successfully."))
            return redirect("catalog:category_list")
    else:
        form = CategoryForm(organization_id=org.pk)

    categories = list_categories(organization_id=org.pk)
    return render(
        request,
        "catalog/category_list.html",
        {"categories": categories, "form": form},
    )


@login_required
def unit_list_view(request: HttpRequest) -> HttpResponse:
    """Manage units of measure."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    if request.method == "POST":
        _check_perm(request, "catalog.manage", org)
        form = UnitForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                create_unit(
                    organization=org,
                    name=data["name"],
                    code=data["code"],
                    precision=data["precision"],
                )
                messages.success(request, _("Unit of measure created."))
                return redirect("catalog:unit_list")
            except CatalogError as err:
                messages.error(request, str(err))
    else:
        form = UnitForm()

    units = list_units(organization_id=org.pk)
    return render(request, "catalog/unit_list.html", {"units": units, "form": form})


@login_required
def pricelist_list_view(request: HttpRequest) -> HttpResponse:
    """Manage price lists."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    if request.method == "POST":
        _check_perm(request, "catalog.manage", org)
        form = PriceListForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            create_price_list(
                organization=org,
                name=data["name"],
                currency=data.get("currency", "USD"),
                is_default=data.get("is_default", False),
                description=data.get("description", ""),
                actor=request.user,
            )
            messages.success(request, _("Price list created."))
            return redirect("catalog:pricelist_list")
    else:
        form = PriceListForm()

    price_lists = list_price_lists(organization_id=org.pk)
    return render(
        request,
        "catalog/pricelist_list.html",
        {"price_lists": price_lists, "form": form},
    )


@login_required
def pricelist_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View and manage items in a price list."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    price_list = get_object_or_404(PriceList.all_tenants, organization=org, pk=pk)

    if request.method == "POST":
        _check_perm(request, "catalog.manage", org)
        form = PriceListItemForm(request.POST, organization_id=org.pk)
        if form.is_valid():
            data = form.cleaned_data
            product = get_object_or_404(Product.all_tenants, organization=org, pk=data["product_id"])
            set_price_list_item(
                price_list=price_list,
                product=product,
                price=data["price"],
                min_quantity=data["min_quantity"],
            )
            messages.success(request, _("Price list item updated."))
            return redirect("catalog:pricelist_detail", pk=price_list.pk)
    else:
        form = PriceListItemForm(organization_id=org.pk)

    items = get_price_list_items(organization_id=org.pk, price_list_id=price_list.pk)
    return render(
        request,
        "catalog/pricelist_detail.html",
        {"price_list": price_list, "items": items, "form": form},
    )


@login_required
@require_GET
def export_csv_view(request: HttpRequest) -> HttpResponse:
    """Download CSV file of all products."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.view", org)

    csv_data = export_products_csv(organization=org)
    response = HttpResponse(csv_data, content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="products_export.csv"'
    return response


@login_required
@require_POST
def import_csv_view(request: HttpRequest) -> HttpResponse:
    """Import products from uploaded CSV file."""
    org = _get_active_org(request)
    _check_perm(request, "catalog.manage", org)

    form = CsvImportForm(request.POST, request.FILES)
    if form.is_valid():
        uploaded = form.cleaned_data["csv_file"]
        update_existing = form.cleaned_data["update_existing"]
        content = uploaded.read().decode("utf-8-sig", errors="replace")

        result = import_products_csv(
            organization=org,
            csv_content=content,
            update_existing=update_existing,
            actor=request.user,
        )

        msg = _("CSV Import Complete: %(created)d created, %(updated)d updated, %(skipped)d skipped.") % {
            "created": result["created"],
            "updated": result["updated"],
            "skipped": result["skipped"],
        }
        messages.success(request, msg)

        if result["errors"]:
            for err in result["errors"][:5]:
                messages.warning(request, err)
    else:
        messages.error(request, _("Invalid CSV upload form."))

    return redirect("catalog:product_list")
