from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import check_object_scope, permission_required, scope_queryset
from apps.pos import selectors, services
from apps.pos.exceptions import POSError
from apps.pos.forms import POSCloseShiftForm, POSOpenShiftForm
from apps.pos.models import POSShiftStatus
from apps.pos.views.common import _get_org


@permission_required("pos.shift_open")
def shift_open_view(request: HttpRequest) -> HttpResponse:
    """Open a new cashier shift."""
    org = _get_org(request)

    if request.method == "POST":
        form = POSOpenShiftForm(request.POST, organization=org, user=request.user)
        if form.is_valid():
            try:
                shift = services.open_shift(
                    organization=org,
                    register=form.cleaned_data["register"],
                    cashier=request.user,
                    opening_cash=form.cleaned_data["opening_cash"],
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Shift %(num)s opened on %(reg)s.")
                    % {"num": shift.shift_number, "reg": shift.register.code},
                )
                return redirect("pos:terminal")
            except POSError as err:
                messages.error(request, str(err))
        else:
            messages.error(request, _("Please correct the form errors below."))
    else:
        form = POSOpenShiftForm(organization=org, user=request.user)

    return render(request, "pos/shift_open.html", {"form": form})


@permission_required("pos.shift_close")
def shift_close_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Close an active cashier shift and review cash variance."""
    org = _get_org(request)
    shift = selectors.get_shift(organization=org, public_id=public_id)
    if not shift or not check_object_scope(request.user, shift, organization=org):
        raise PermissionDenied(_("Shift not found."))

    if request.method == "POST":
        form = POSCloseShiftForm(request.POST)
        if form.is_valid():
            try:
                closed_shift = services.close_shift(
                    organization=org,
                    shift=shift,
                    closing_cash_counted=form.cleaned_data["closing_cash_counted"],
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Shift %(num)s closed successfully. Variance: $%(var)s.")
                    % {"num": closed_shift.shift_number, "var": closed_shift.cash_variance},
                )
                return redirect("pos:shift_detail", public_id=closed_shift.public_id)
            except POSError as err:
                messages.error(request, str(err))
        else:
            messages.error(request, _("Invalid cash count entered."))

    return redirect("pos:shift_detail", public_id=shift.public_id)


@permission_required("pos.access")
def shift_list_view(request: HttpRequest) -> HttpResponse:
    """List all cashier shifts with status filters."""
    org = _get_org(request)
    status_filter = request.GET.get("status") or None
    shifts = selectors.list_shifts(organization=org, status=status_filter)
    shifts = scope_queryset(shifts, request.user, organization=org)

    return render(
        request,
        "pos/shift_list.html",
        {
            "shifts": shifts,
            "status_filter": status_filter,
        },
    )


@permission_required("pos.access")
def shift_detail_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """View shift summary, sales, and closing cash variance audit."""
    org = _get_org(request)
    shift = selectors.get_shift(organization=org, public_id=public_id)
    if not shift or not check_object_scope(request.user, shift, organization=org):
        raise PermissionDenied(_("Shift not found."))

    sales = selectors.list_sales(organization=org, shift_id=shift.pk)

    context = {
        "shift": shift,
        "sales": sales,
        "close_form": POSCloseShiftForm() if shift.status == POSShiftStatus.OPEN else None,
    }
    return render(request, "pos/shift_detail.html", context)

