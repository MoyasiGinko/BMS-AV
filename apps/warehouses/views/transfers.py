"""Stock transfers views: inter-warehouse shipments, transfers tracking, and dispatch/receive."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.catalog.models import Product, ProductVariant
from apps.core.permissions import check_object_scope, scope_queryset
from apps.inventory.models import StockTransfer
from apps.tenancy.models import Warehouse
from apps.warehouses import selectors, services
from apps.warehouses.forms import StockTransferForm
from apps.warehouses.views.common import (
    ValidationError,
)
from apps.warehouses.views.common import (
    can_manage as _can_manage,
)
from apps.warehouses.views.common import (
    can_view as _can_view,
)
from apps.warehouses.views.common import (
    get_org as _get_org,
)


@login_required
@require_http_methods(["GET"])
def transfer_list_view(request: HttpRequest) -> HttpResponse:
    """List inter-warehouse stock transfer documents."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view transfers."))

    transfers = selectors.list_stock_transfers(organization=org)
    transfers = scope_queryset(transfers, request.user, organization=org)

    src_filter = request.GET.get("source_warehouse")
    dst_filter = request.GET.get("destination_warehouse")
    status_filter = request.GET.get("status")

    if src_filter and src_filter.isdigit():
        transfers = transfers.filter(source_warehouse_id=int(src_filter))
    if dst_filter and dst_filter.isdigit():
        transfers = transfers.filter(destination_warehouse_id=int(dst_filter))
    if status_filter:
        transfers = transfers.filter(status=status_filter)

    paginator = Paginator(transfers, 20)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    warehouses = selectors.list_warehouses(organization=org, active_only=True)

    return render(
        request,
        "warehouses/transfer_list.html",
        {
            "organization": org,
            "page_obj": page_obj,
            "warehouses": warehouses,
            "selected_source": src_filter,
            "selected_destination": dst_filter,
            "selected_status": status_filter,
            "can_manage": _can_manage(request.user, org),
            "active_subtab": "transfers",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def transfer_create_view(request: HttpRequest) -> HttpResponse:
    """Create and complete an inter-warehouse stock transfer."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to transfer stock."))

    if request.method == "POST":
        form = StockTransferForm(request.POST, organization=org)
        if form.is_valid():
            src_wh = get_object_or_404(
                Warehouse.all_tenants, organization=org, pk=form.cleaned_data["source_warehouse_id"]
            )
            dest_wh = get_object_or_404(
                Warehouse.all_tenants, organization=org, pk=form.cleaned_data["destination_warehouse_id"]
            )
            prod = get_object_or_404(Product.all_tenants, organization=org, pk=form.cleaned_data["product_id"])
            var_id = form.cleaned_data.get("variant_id")
            variant = (
                ProductVariant.all_tenants.filter(organization=org, pk=var_id).first()
                if var_id
                else None
            )

            if src_wh.pk == dest_wh.pk:
                messages.error(request, _("Source and destination warehouses cannot be the same."))
            else:
                try:
                    trf = services.transfer_stock(
                        organization=org,
                        source_warehouse=src_wh,
                        destination_warehouse=dest_wh,
                        lines=[
                            {
                                "product": prod,
                                "variant": variant,
                                "quantity": form.cleaned_data["quantity"],
                            }
                        ],
                        notes=form.cleaned_data.get("notes", ""),
                        actor=request.user,
                    )
                    messages.success(
                        request,
                        _("Stock transfer %(num)s completed successfully.")
                        % {"num": trf.transfer_number},
                    )
                    return redirect("warehouses:transfer_detail", pk=trf.pk)
                except ValidationError as exc:
                    messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
                except Exception as err:
                    messages.error(request, str(err))
    else:
        form = StockTransferForm(organization=org)

    return render(
        request,
        "warehouses/transfer_form.html",
        {
            "organization": org,
            "form": form,
            "active_subtab": "transfers",
        },
    )


@login_required
@require_http_methods(["GET"])
def transfer_detail_view(request: HttpRequest, pk: int | None = None, public_id: Any = None) -> HttpResponse:
    """Detail view for a stock transfer and its individual product line items."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view transfers."))

    if pk:
        trf = selectors.get_stock_transfer(organization=org, transfer_id=pk)
    else:
        trf = StockTransfer.all_tenants.filter(organization=org, public_id=public_id).select_related(
            "source_warehouse", "destination_warehouse"
        ).first()

    if not trf:
        messages.error(request, _("Transfer not found."))
        return redirect("warehouses:transfer_list")

    if not check_object_scope(request.user, trf, organization=org):
        raise PermissionDenied(
            _("You do not have permission to view transfers outside your assigned branches.")
        )

    lines = trf.lines.select_related("product", "variant").all()

    return render(
        request,
        "warehouses/transfer_detail.html",
        {
            "organization": org,
            "transfer": trf,
            "lines": lines,
            "can_manage": _can_manage(request.user, org),
            "active_subtab": "transfers",
        },
    )
