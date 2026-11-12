"""Web views for branch-to-warehouse stock returns, condition inspection, and replacements."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from apps.core.permissions import permission_required
from apps.inventory import selectors, services
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


@permission_required("inventory.manage")
def stock_return_inspect_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Warehouse inspects and accepts returned items into inventory, quarantine, or scrap."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    notes = request.POST.get("inspection_notes", "").strip()
    inspections: list[dict[str, Any]] = []

    for line in stock_request.lines.all():
        disp = request.POST.get(f"disposition_{line.id}") or "restock_sellable"
        cond = request.POST.get(f"condition_{line.id}") or line.item_condition or "good"
        line_notes = request.POST.get(f"notes_{line.id}", "").strip()
        inspections.append({
            "line_id": line.id,
            "disposition": disp,
            "item_condition": cond,
            "inspection_notes": line_notes,
        })

    try:
        services.inspect_and_accept_stock_return(
            organization=org,
            transfer=stock_request,
            inspections=inspections,
            actor=request.user,
            notes=notes,
        )
        messages.success(
            request,
            _("Return %(num)s inspected and accepted. Stock ledger updated.")
            % {"num": stock_request.transfer_number},
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)


@permission_required("inventory.manage")
def stock_replacement_dispatch_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Warehouse dispatches replacement stock to the outlet."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("inventory:stock_request_detail", pk=pk)

    stock_request = selectors.get_branch_stock_request(organization_id=org.pk, transfer_id=pk)
    if not stock_request:
        messages.error(request, _("Stock request not found."))
        return redirect("inventory:stock_request_list")

    tracking_num = request.POST.get("tracking_number", "").strip()
    carrier = request.POST.get("carrier", "").strip()

    try:
        services.dispatch_replacement_stock(
            organization=org,
            transfer=stock_request,
            actor=request.user,
            tracking_number=tracking_num,
            carrier=carrier,
        )
        target_name = (
            stock_request.source_branch.name
            if stock_request.source_branch
            else _("outlet")
        )
        messages.success(
            request,
            _("Replacement stock for %(num)s dispatched to %(branch)s.")
            % {
                "num": stock_request.transfer_number,
                "branch": target_name,
            },
        )
    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("inventory:stock_request_detail", pk=pk)

