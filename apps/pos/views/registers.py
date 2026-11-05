from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import permission_required, scope_queryset
from apps.pos import selectors, services
from apps.pos.forms import POSRegisterForm
from apps.pos.views.common import _get_org


@permission_required("pos.manage")
def register_list_view(request: HttpRequest) -> HttpResponse:
    """List all POS terminals."""
    org = _get_org(request)
    registers = selectors.list_registers(organization=org)
    registers = scope_queryset(registers, request.user, organization=org)
    return render(request, "pos/register_list.html", {"registers": registers})


@permission_required("pos.manage")
def register_create_view(request: HttpRequest) -> HttpResponse:
    """Create a new POS terminal."""
    org = _get_org(request)
    if request.method == "POST":
        form = POSRegisterForm(request.POST, organization=org)
        if form.is_valid():
            try:
                reg = services.create_register(
                    organization=org,
                    name=form.cleaned_data["name"],
                    branch=form.cleaned_data["branch"],
                    warehouse=form.cleaned_data["warehouse"],
                    code=form.cleaned_data.get("code") or None,
                    receipt_header=form.cleaned_data.get("receipt_header", ""),
                    receipt_footer=form.cleaned_data.get("receipt_footer", ""),
                    is_active=form.cleaned_data.get("is_active", True),
                    actor=request.user,
                )
                messages.success(request, _("Register %s created successfully.") % reg.code)
                return redirect("pos:register_list")
            except Exception as exc:
                messages.error(request, str(exc))
    else:
        form = POSRegisterForm(organization=org)

    return render(request, "pos/register_form.html", {"form": form})

