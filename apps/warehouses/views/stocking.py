"""Views for stocking products and raw ingredients into warehouses and tracking intake records."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import (
    InventoryLocation,
    StockMovement,
    WarehouseStorageType,
)
from apps.warehouses import selectors, services
from apps.warehouses.models import Warehouse
from apps.warehouses.views.common import can_manage, can_view, get_org


@login_required
@require_http_methods(["GET"])
def stock_intake_list_view(request: HttpRequest) -> HttpResponse:
    """List historical warehouse stock intake receipts and records with search & filters."""
    org = get_org(request)
    if not can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view stock intakes."))

    wh_id_raw = request.GET.get("warehouse")
    wh_id = int(wh_id_raw) if wh_id_raw and wh_id_raw.isdigit() else None
    query = request.GET.get("q", "").strip()
    date_from_raw = request.GET.get("date_from", "").strip()
    date_to_raw = request.GET.get("date_to", "").strip()

    date_from = parse_date(date_from_raw) if date_from_raw else None
    date_to = parse_date(date_to_raw) if date_to_raw else None

    intakes_qs = selectors.list_stock_intakes(
        organization=org,
        warehouse_id=wh_id,
        query=query,
        date_from=date_from,
        date_to=date_to,
    )

    # Compute KPI totals across filtered records
    total_records = intakes_qs.count()
    total_qty_stocked = Decimal("0.0000")
    total_cost_added = Decimal("0.0000")
    for intake in intakes_qs:
        total_qty_stocked += intake.total_quantity or Decimal("0.0000")
        total_cost_added += intake.total_cost or Decimal("0.0000")

    paginator = Paginator(intakes_qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    warehouses = selectors.list_warehouses(organization=org, active_only=True)

    return render(
        request,
        "warehouses/stock_intake_list.html",
        {
            "organization": org,
            "intakes": page_obj,
            "page_obj": page_obj,
            "warehouses": warehouses,
            "selected_warehouse": wh_id,
            "query": query,
            "date_from": date_from_raw,
            "date_to": date_to_raw,
            "total_records": total_records,
            "total_qty_stocked": total_qty_stocked,
            "total_cost_added": total_cost_added,
            "can_manage": can_manage(request.user, org),
            "active_subtab": "stocking",
        },
    )


def _parse_intake_lines(request: HttpRequest, org: Any) -> list[dict[str, Any]]:
    """Parse dynamic product and ingredient lines from form post."""
    product_ids = request.POST.getlist("product_id[]")
    variant_ids = request.POST.getlist("variant_id[]")
    quantities = request.POST.getlist("quantity[]")
    unit_costs = request.POST.getlist("unit_cost[]")
    batch_numbers = request.POST.getlist("batch_number[]")
    expiry_dates = request.POST.getlist("expiry_date[]")
    line_notes = request.POST.getlist("line_notes[]")

    lines_data: list[dict[str, Any]] = []
    for i in range(len(product_ids)):
        p_id = product_ids[i].strip() if i < len(product_ids) else ""
        if not p_id or not p_id.isdigit():
            continue

        product = Product.all_tenants.filter(organization=org, pk=int(p_id)).first()
        if not product:
            continue

        v_id = variant_ids[i].strip() if i < len(variant_ids) else ""
        variant = ProductVariant.all_tenants.filter(organization=org, pk=int(v_id)).first() if v_id and v_id.isdigit() else None

        qty_raw = quantities[i] if i < len(quantities) else "1"
        try:
            qty = Decimal(str(qty_raw))
        except (InvalidOperation, TypeError):
            qty = Decimal("1.0000")

        cost_raw = unit_costs[i] if i < len(unit_costs) else ""
        try:
            cost = Decimal(str(cost_raw)) if cost_raw else (product.cost_price or Decimal("0.0000"))
        except (InvalidOperation, TypeError):
            cost = product.cost_price or Decimal("0.0000")

        batch_num = batch_numbers[i].strip() if i < len(batch_numbers) else ""
        exp_raw = expiry_dates[i].strip() if i < len(expiry_dates) else ""
        exp_date = parse_date(exp_raw) if exp_raw else None
        l_notes = line_notes[i].strip() if i < len(line_notes) else ""

        lines_data.append({
            "product": product,
            "variant": variant,
            "quantity": qty,
            "unit_cost": cost,
            "batch_number": batch_num,
            "expiry_date": exp_date,
            "notes": l_notes,
        })
    return lines_data


def _handle_stock_intake_post(request: HttpRequest, org: Any) -> HttpResponse:
    """Process stock intake form submission and redirect on completion or error."""
    wh_id = request.POST.get("warehouse_id")
    storage_type_id = request.POST.get("storage_type_id")
    location_id = request.POST.get("location_id")
    intake_type = request.POST.get("intake_type", "purchase_receipt").strip()
    ref_no = request.POST.get("reference_number", "").strip()
    supplier_name = request.POST.get("supplier_name", "").strip()
    notes = request.POST.get("notes", "").strip()
    date_raw = request.POST.get("date", "").strip()
    intake_date = parse_date(date_raw) if date_raw else timezone.now().date()

    if not wh_id:
        messages.error(request, _("Please select a target warehouse facility."))
        return redirect("warehouses:stock_intake_create")

    warehouse = get_object_or_404(Warehouse.all_tenants, organization=org, pk=wh_id)

    storage_type = None
    if storage_type_id and storage_type_id.isdigit():
        storage_type = WarehouseStorageType.all_tenants.filter(organization=org, pk=int(storage_type_id)).first()

    location = None
    if location_id and location_id.isdigit():
        location = InventoryLocation.all_tenants.filter(organization=org, pk=int(location_id)).first()

    lines_data = _parse_intake_lines(request, org)
    if not lines_data:
        messages.error(request, _("Please add at least one product or ingredient to stock."))
        return redirect("warehouses:stock_intake_create")

    try:
        intake = services.create_stock_intake(
            organization=org,
            warehouse=warehouse,
            storage_type=storage_type,
            location=location,
            intake_type=intake_type,
            reference_number=ref_no,
            supplier_name=supplier_name,
            date=intake_date,
            notes=notes,
            lines=lines_data,
            actor=request.user,
        )
        messages.success(
            request,
            _("Stock intake %(num)s created. %(count)d items recorded into warehouse storage.")
            % {"num": intake.intake_number, "count": len(lines_data)},
        )
        return redirect("warehouses:stock_intake_detail", pk=intake.pk)
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("warehouses:stock_intake_create")


def _build_intake_form_context(request: HttpRequest, org: Any) -> dict[str, Any]:
    """Prepare context dictionary with product catalog and warehouse choices for intake form."""
    initial_wh_id_raw = request.GET.get("warehouse")
    warehouses = selectors.list_warehouses(organization=org, active_only=True)
    if initial_wh_id_raw and initial_wh_id_raw.isdigit():
        initial_wh_id = int(initial_wh_id_raw)
    else:
        default_wh = next((w for w in warehouses if w.is_default), warehouses[0] if warehouses else None)
        initial_wh_id = default_wh.pk if default_wh else None

    storage_types = selectors.list_warehouse_storage_types(organization=org, active_only=True)
    products = (
        Product.all_tenants.filter(organization=org, is_active=True)
        .select_related("category", "unit")
        .prefetch_related("images", "variants")
        .order_by("name")
    )

    products_data: dict[str, dict[str, Any]] = {}
    for p in products:
        img_url = ""
        try:
            first_img = p.images.first()
            if first_img and first_img.image:
                img_url = first_img.image.url
        except Exception:
            img_url = ""

        cat_name = p.category.name.lower() if p.category else ""
        p_name = p.name.lower()
        is_ing = (
            getattr(p, "is_raw_material", False)
            or ("ingredient" in cat_name or "raw" in cat_name or "spice" in cat_name or "material" in cat_name)
            or ("ingredient" in p_name or "raw" in p_name)
        )

        products_data[str(p.pk)] = {
            "id": p.pk,
            "name": p.name,
            "sku": p.sku or "",
            "upc": p.barcode or "",
            "category": p.category.name if p.category else "",
            "unit": p.unit.code if p.unit else _("units"),
            "cost_price": str(p.cost_price or Decimal("0.0000")),
            "image": img_url,
            "is_ingredient": is_ing,
            "variants": [
                {
                    "id": v.id,
                    "name": v.name,
                    "sku": v.sku or "",
                    "cost_price": str(v.cost_price or p.cost_price or Decimal("0.0000")),
                }
                for v in p.variants.filter(is_active=True)
            ],
        }

    return {
        "organization": org,
        "warehouses": warehouses,
        "storage_types": storage_types,
        "products": products,
        "products_data": products_data,
        "initial_wh_id": initial_wh_id,
        "today": timezone.now().date(),
        "active_subtab": "stocking",
    }


@login_required
@require_http_methods(["GET", "POST"])
def stock_intake_create_view(request: HttpRequest) -> HttpResponse:
    """Stock products or raw ingredients into warehouse inventory with dynamic lines."""
    org = get_org(request)
    if not can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to stock inventory."))

    if request.method == "POST":
        return _handle_stock_intake_post(request, org)

    ctx = _build_intake_form_context(request, org)
    return render(request, "warehouses/stock_intake_form.html", ctx)


@login_required
@require_http_methods(["GET"])
def stock_intake_detail_view(request: HttpRequest, pk: int) -> HttpResponse:
    """View receipt details of a warehouse stock intake with immutable ledger movements."""
    org = get_org(request)
    if not can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view stock intake details."))

    intake = selectors.get_stock_intake(organization=org, intake_id=pk)
    if not intake:
        messages.error(request, _("Stock intake record not found."))
        return redirect("warehouses:stock_intake_list")

    lines = intake.lines.select_related("product__category", "product__unit", "variant").all()

    # Query linked stock ledger movements posted during intake
    ledger_movements = (
        StockMovement.objects.filter(
            organization=org,
            reference_type="inventory.StockIntake",
            reference_id=str(intake.pk),
        )
        .select_related("warehouse", "product", "created_by")
        .order_by("id")
    )

    return render(
        request,
        "warehouses/stock_intake_detail.html",
        {
            "organization": org,
            "intake": intake,
            "lines": lines,
            "ledger_movements": ledger_movements,
            "can_manage": can_manage(request.user, org),
            "active_subtab": "stocking",
        },
    )
