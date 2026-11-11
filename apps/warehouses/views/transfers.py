"""Stock transfers views: inter-warehouse shipments, transfers tracking, and dispatch/receive."""

from __future__ import annotations

import contextlib
from decimal import Decimal, InvalidOperation
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
from apps.inventory.models import InventoryLocation, StockMovement, StockTransfer, StorageType, TransferStatus
from apps.tenancy.models import Warehouse
from apps.warehouses import selectors, services
from apps.warehouses.forms import (
    TransferDispatchForm,
    TransferReceiveForm,
    TransferRejectForm,
    WarehouseStockTransferForm,
)
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


def _handle_transfer_create_post(
    request: HttpRequest, org: Any, form: WarehouseStockTransferForm
) -> HttpResponse | None:
    src_wh = get_object_or_404(
        Warehouse.all_tenants, organization=org, pk=form.cleaned_data["source_warehouse_id"]
    )
    dest_wh = get_object_or_404(
        Warehouse.all_tenants, organization=org, pk=form.cleaned_data["destination_warehouse_id"]
    )
    # Dynamically resolve source storage location
    src_st_code = form.cleaned_data.get("source_storage_type", "").strip()
    src_loc = None
    if src_st_code.isdigit():
        src_loc = InventoryLocation.all_tenants.filter(organization=org, warehouse=src_wh, pk=int(src_st_code)).first()
    if not src_loc and src_st_code:
        src_loc = (
            InventoryLocation.all_tenants.filter(
                organization=org, warehouse=src_wh, custom_storage_type__code__iexact=src_st_code, is_active=True
            ).first()
            or InventoryLocation.all_tenants.filter(
                organization=org, warehouse=src_wh, storage_type__iexact=src_st_code, is_active=True
            ).first()
        )
    if not src_loc:
        src_loc = (
            src_wh.get_internal_location()
            if src_st_code == StorageType.INTERNAL_USE
            else src_wh.get_sellable_location()
        )

    # Dynamically resolve destination storage location
    dest_st_code = form.cleaned_data.get("destination_storage_type", "").strip()
    dest_loc = None
    if dest_st_code.isdigit():
        dest_loc = InventoryLocation.all_tenants.filter(organization=org, warehouse=dest_wh, pk=int(dest_st_code)).first()
    if not dest_loc and dest_st_code:
        dest_loc = (
            InventoryLocation.all_tenants.filter(
                organization=org, warehouse=dest_wh, custom_storage_type__code__iexact=dest_st_code, is_active=True
            ).first()
            or InventoryLocation.all_tenants.filter(
                organization=org, warehouse=dest_wh, storage_type__iexact=dest_st_code, is_active=True
            ).first()
        )
    if not dest_loc:
        dest_loc = (
            dest_wh.get_internal_location()
            if dest_st_code == StorageType.INTERNAL_USE
            else dest_wh.get_sellable_location()
        )

    if src_wh.pk == dest_wh.pk and src_loc.pk == dest_loc.pk:
        messages.error(request, _("Source and destination storage location cannot be the same."))
        return None

    prod = get_object_or_404(Product.all_tenants, organization=org, pk=form.cleaned_data["product_id"])
    var_id = form.cleaned_data.get("variant_id")
    variant = ProductVariant.all_tenants.filter(organization=org, pk=var_id).first() if var_id else None

    lines_data = [{"product": prod, "variant": variant, "quantity": form.cleaned_data["quantity"]}]
    notes = form.cleaned_data.get("notes", "")
    mode = form.cleaned_data.get("mode", "request")

    try:
        if mode == "direct":
            trf = services.transfer_stock(
                organization=org,
                source_warehouse=src_wh,
                destination_warehouse=dest_wh,
                lines=lines_data,
                notes=notes,
                actor=request.user,
            )
            messages.success(
                request,
                _("Stock transfer %(num)s completed directly with ledger records posted.")
                % {"num": trf.transfer_number},
            )
        else:
            trf = services.create_stock_transfer(
                organization=org,
                source_warehouse=src_wh,
                destination_warehouse=dest_wh,
                source_location=src_loc,
                destination_location=dest_loc,
                lines=lines_data,
                status=TransferStatus.PENDING_APPROVAL,
                notes=notes,
                actor=request.user,
            )
            messages.success(
                request,
                _("Stock transfer request %(num)s submitted for approval.")
                % {"num": trf.transfer_number},
            )
        return redirect("warehouses:transfer_detail", pk=trf.pk)
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))
    except Exception as err:
        messages.error(request, str(err))
    return None


@login_required
@require_http_methods(["GET", "POST"])
def transfer_create_view(request: HttpRequest) -> HttpResponse:
    """Create a stock transfer request or execute direct transfer between storage zones."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to transfer stock."))

    if request.method == "POST":
        form = WarehouseStockTransferForm(request.POST, organization=org)
        if form.is_valid():
            redirect_response = _handle_transfer_create_post(request, org, form)
            if redirect_response:
                return redirect_response
    else:
        initial = {}
        dest_branch_id = request.GET.get("destination_branch")
        if dest_branch_id and dest_branch_id.isdigit():
            from apps.warehouses.selectors import get_default_warehouse_for_branch  # noqa: PLC0415

            wh = get_default_warehouse_for_branch(organization=org, branch_id=int(dest_branch_id))
            if wh:
                initial["destination_warehouse_id"] = wh.pk
            else:
                wh = (
                    Warehouse.all_tenants.filter(organization=org, branch_id=dest_branch_id, is_active=True)
                    .first()
                )
                if wh:
                    initial["destination_warehouse_id"] = wh.pk

        if request.GET.get("destination_warehouse"):
            initial["destination_warehouse_id"] = request.GET.get("destination_warehouse")
        if request.GET.get("source_warehouse"):
            initial["source_warehouse_id"] = request.GET.get("source_warehouse")
        if request.GET.get("product_id"):
            initial["product_id"] = request.GET.get("product_id")

        form = WarehouseStockTransferForm(organization=org, initial=initial)

    storage_types = selectors.list_warehouse_storage_types(organization=org, active_only=True)

    return render(
        request,
        "warehouses/transfer_form.html",
        {
            "organization": org,
            "form": form,
            "storage_types": storage_types,
            "active_subtab": "transfers",
        },
    )


@login_required
@require_http_methods(["GET"])
def transfer_detail_view(request: HttpRequest, pk: int | None = None, public_id: Any = None) -> HttpResponse:
    """Detail view for a stock transfer with dual-end validation stepper and immutable movement ledger."""
    org = _get_org(request)
    if not _can_view(request.user, org):
        raise PermissionDenied(_("You do not have permission to view transfers."))

    if pk:
        trf = selectors.get_stock_transfer(organization=org, transfer_id=pk)
    else:
        trf = StockTransfer.all_tenants.filter(organization=org, public_id=public_id).select_related(
            "source_warehouse", "destination_warehouse", "source_location", "destination_location"
        ).first()

    if not trf:
        messages.error(request, _("Transfer not found."))
        return redirect("warehouses:transfer_list")

    if not check_object_scope(request.user, trf, organization=org):
        raise PermissionDenied(
            _("You do not have permission to view transfers outside your assigned branches.")
        )

    lines = trf.lines.select_related("product", "variant").all()

    # Immutable movement ledger records tied to this transfer
    movements = StockMovement.all_tenants.filter(
        organization=org,
        reference_type="inventory.StockTransfer",
        reference_id=str(trf.pk),
    ).select_related("product", "variant", "warehouse", "location", "created_by").order_by("occurred_at")

    can_manage = _can_manage(request.user, org)

    return render(
        request,
        "warehouses/transfer_detail.html",
        {
            "organization": org,
            "transfer": trf,
            "lines": lines,
            "movements": movements,
            "can_manage": can_manage,
            "dispatch_form": TransferDispatchForm(),
            "receive_form": TransferReceiveForm(),
            "reject_form": TransferRejectForm(),
            "active_subtab": "transfers",
        },
    )


@login_required
@require_http_methods(["POST"])
def transfer_approve_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Approve a pending stock transfer request."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to approve transfers."))

    trf = get_object_or_404(StockTransfer.all_tenants, organization=org, pk=pk)
    try:
        services.approve_stock_transfer(organization=org, transfer=trf, actor=request.user)
        messages.success(request, _("Transfer %(num)s approved. Ready for dispatch.") % {"num": trf.transfer_number})
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("warehouses:transfer_detail", pk=pk)


@login_required
@require_http_methods(["POST"])
def transfer_reject_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Reject a pending stock transfer request with recorded reason."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to reject transfers."))

    trf = get_object_or_404(StockTransfer.all_tenants, organization=org, pk=pk)
    reason = request.POST.get("rejection_reason", "").strip()
    try:
        services.reject_stock_transfer(organization=org, transfer=trf, reason=reason, actor=request.user)
        messages.warning(request, _("Transfer %(num)s rejected.") % {"num": trf.transfer_number})
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("warehouses:transfer_detail", pk=pk)


@login_required
@require_http_methods(["POST"])
def transfer_dispatch_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Dispatch shipment: sender verification, carrier details, and outbound movement ledger posting."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to dispatch transfers."))

    trf = get_object_or_404(StockTransfer.all_tenants, organization=org, pk=pk)
    carrier = request.POST.get("carrier", "").strip()
    tracking = request.POST.get("tracking_number", "").strip()

    try:
        services.dispatch_stock_transfer(
            organization=org,
            transfer=trf,
            carrier=carrier,
            tracking_number=tracking,
            actor=request.user,
        )
        messages.success(
            request,
            _("Transfer %(num)s dispatched. Outbound stock movement recorded in ledger.")
            % {"num": trf.transfer_number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("warehouses:transfer_detail", pk=pk)


@login_required
@require_http_methods(["POST"])
def transfer_receive_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Intake intake verification: receiver dual sign-off, damage/loss adjustment, and inbound ledger posting."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to receive transfers."))

    trf = get_object_or_404(StockTransfer.all_tenants, organization=org, pk=pk)
    notes = request.POST.get("receive_notes", "").strip()

    # Build receipt lines from line inputs
    lines = list(trf.lines.all())
    receipt_lines = []
    for line in lines:
        prefix = f"line_{line.id}_"
        recv_str = request.POST.get(f"{prefix}received")
        dmg_str = request.POST.get(f"{prefix}damaged", "0")
        mis_str = request.POST.get(f"{prefix}missing", "0")

        if recv_str is not None:
            with contextlib.suppress(InvalidOperation, ValueError):
                receipt_lines.append(
                    {
                        "line_id": line.id,
                        "quantity_received": Decimal(recv_str),
                        "quantity_damaged": Decimal(dmg_str or "0"),
                        "quantity_missing": Decimal(mis_str or "0"),
                    }
                )

    try:
        services.receive_stock_transfer(
            organization=org,
            transfer=trf,
            receipt_lines=receipt_lines or None,
            notes=notes,
            actor=request.user,
        )
        messages.success(
            request,
            _("Transfer %(num)s intake received and verified. Inbound stock movement recorded in ledger.")
            % {"num": trf.transfer_number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("warehouses:transfer_detail", pk=pk)


@login_required
@require_http_methods(["POST"])
def transfer_cancel_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Cancel a transfer before dispatch."""
    org = _get_org(request)
    if not _can_manage(request.user, org):
        raise PermissionDenied(_("You do not have permission to cancel transfers."))

    trf = get_object_or_404(StockTransfer.all_tenants, organization=org, pk=pk)
    try:
        services.cancel_stock_transfer(organization=org, transfer=trf, actor=request.user)
        messages.info(request, _("Transfer %(num)s cancelled.") % {"num": trf.transfer_number})
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("warehouses:transfer_detail", pk=pk)
