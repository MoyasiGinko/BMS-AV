"""Web views and HTMX partial endpoints for the Point of Sale (POS) module."""

from __future__ import annotations

import contextlib
import json
import threading
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product
from apps.core.permissions import check_object_scope, permission_required, scope_queryset
from apps.customers.models import Customer
from apps.pos import printing, selectors, services
from apps.pos.exceptions import POSError
from apps.pos.forms import (
    POSCloseShiftForm,
    POSOpenShiftForm,
    POSRegisterForm,
)
from apps.pos.models import POSShift, POSShiftStatus
from apps.sales.models import PaymentMethod
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization context found."))
    return org


@permission_required("pos.access")
def terminal_view(request: HttpRequest) -> HttpResponse:
    """Fast counter checkout terminal view."""
    org = _get_org(request)

    # 1. Check for active open shift for this user
    active_shift = selectors.get_active_shift_for_user(organization=org, user=request.user)
    if active_shift and not check_object_scope(request.user, active_shift, organization=org):
        active_shift = None

    # If no shift open, check if register requested or redirect to open shift
    register_id = request.GET.get("register")
    selected_register = None
    if register_id and register_id.isdigit():
        reg = selectors.get_register(organization=org, register_id=int(register_id))
        if reg and check_object_scope(request.user, reg, organization=org):
            selected_register = reg

    registers = scope_queryset(
        selectors.list_registers(organization=org, is_active=True),
        request.user,
        organization=org,
    )

    if not active_shift:
        # If no register exists at all, prompt creating one
        if not registers.exists():
            messages.info(request, _("Please configure at least one POS register first."))
            return redirect("pos:register_create")

        # Prompt user to open shift
        return render(
            request,
            "pos/terminal_no_shift.html",
            {
                "registers": registers,
                "selected_register": selected_register or registers.first(),
                "open_form": POSOpenShiftForm(
                    organization=org,
                    user=request.user,
                    initial={"register": selected_register or registers.first()},
                ),
            },
        )

    # Shift is open - load products, categories, held carts, and customer list
    search = request.GET.get("search")
    category_id = request.GET.get("category")
    cat_id = int(category_id) if category_id and category_id.isdigit() else None

    products = selectors.get_pos_catalog_products(
        organization=org,
        search=search,
        category_id=cat_id,
        warehouse=active_shift.register.warehouse,
    )
    categories = selectors.get_pos_categories(organization=org)
    held_carts = selectors.list_held_carts(organization=org, shift_id=active_shift.pk)
    customers = Customer.all_tenants.filter(organization=org, status="active").order_by("name")[:50]
    system_printers = selectors.get_system_printers()
    payment_methods = selectors.list_active_payment_methods(organization=org)

    context = {
        "shift": active_shift,
        "register": active_shift.register,
        "products": products,
        "categories": categories,
        "selected_category_id": cat_id,
        "held_carts": held_carts,
        "customers": customers,
        "close_form": POSCloseShiftForm(),
        "system_printers": system_printers,
        "system_printers_json": json.dumps(system_printers),
        "payment_methods": payment_methods,
        "payment_methods_json": json.dumps(payment_methods),
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "pos/partials/product_grid.html", context)

    return render(request, "pos/terminal.html", context)


def _parse_cart_lines(org: Organization, raw_lines: Any) -> list[dict[str, Any]]:
    if isinstance(raw_lines, str):
        with contextlib.suppress(Exception):
            raw_lines = json.loads(raw_lines)
    if not isinstance(raw_lines, list):
        return []
    cart_lines = []
    for item in raw_lines:
        prod_id = item.get("product_id")
        prod = get_object_or_404(Product.all_tenants, pk=prod_id, organization=org)
        qty = Decimal(str(item.get("quantity", "1.0000")))
        price = Decimal(str(item.get("unit_price", prod.selling_price)))
        discount = Decimal(str(item.get("discount_percent", "0.00")))
        tax = Decimal(str(item.get("tax_rate", prod.tax_code.rate if prod.tax_code else "0.00")))
        cart_lines.append(
            {
                "product": prod,
                "quantity": qty,
                "unit_price": price,
                "discount_percent": discount,
                "tax_rate": tax,
            }
        )
    return cart_lines


def _parse_tenders(raw_payments: Any) -> list[dict[str, Any]]:
    if isinstance(raw_payments, str):
        with contextlib.suppress(Exception):
            raw_payments = json.loads(raw_payments)
    if not isinstance(raw_payments, list):
        return []
    tenders = []
    for p in raw_payments:
        method = p.get("payment_method", PaymentMethod.CASH)
        amt = Decimal(str(p.get("amount", "0.0000")))
        if amt > Decimal("0.0000"):
            tenders.append({"payment_method": method, "amount": amt})
    return tenders


@permission_required("pos.checkout")
def checkout_action(request: HttpRequest) -> HttpResponse:
    """Process POS checkout submission from terminal."""
    org = _get_org(request)
    if request.method != "POST":
        return redirect("pos:terminal")

    is_json = (
        request.content_type == "application/json"
        or request.headers.get("Accept") == "application/json"
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )

    data = request.POST
    if request.content_type == "application/json":
        with contextlib.suppress(Exception):
            data = json.loads(request.body.decode("utf-8"))

    shift_id = data.get("shift_id")
    if not shift_id:
        err_msg = str(_("Missing shift_id in request."))
        if not is_json:
            messages.error(request, err_msg)
        return (
            JsonResponse({"success": False, "error": err_msg}, status=400)
            if is_json
            else redirect("pos:terminal")
        )

    shift = get_object_or_404(POSShift.all_tenants, pk=shift_id, organization=org)

    cart_lines = _parse_cart_lines(org, data.get("lines", []))
    tenders = _parse_tenders(data.get("payments", []))

    customer = None
    customer_id = data.get("customer_id")
    if customer_id and str(customer_id).isdigit():
        customer = Customer.all_tenants.filter(organization=org, pk=int(customer_id)).first()

    amount_tendered = None
    if data.get("amount_tendered"):
        with contextlib.suppress(Exception):
            amount_tendered = Decimal(str(data.get("amount_tendered")))

    try:
        sale = services.checkout_pos_sale(
            organization=org,
            shift=shift,
            lines=cart_lines,
            payments=tenders,
            customer=customer,
            amount_tendered=amount_tendered,
            notes=data.get("notes", ""),
            actor=request.user,
        )
        printed_to_os = False
        printer_id = data.get("printer_id")
        if printer_id:
            # Spool asynchronously in background thread so checkout completes instantly
            threading.Thread(
                target=printing.spool_receipt_to_printer,
                kwargs={
                    "organization": org,
                    "sale": sale,
                    "printer_name": printer_id,
                },
                daemon=True,
            ).start()
            printed_to_os = True

        if is_json:
            return JsonResponse(
                {
                    "success": True,
                    "receipt_number": sale.receipt_number,
                    "sale_public_id": str(sale.public_id),
                    "receipt_url": f"/pos/receipt/{sale.public_id}/",
                    "change_given": str(sale.change_given),
                    "amount_tendered": str(sale.amount_tendered),
                    "printed_to_os": printed_to_os,
                }
            )
        messages.success(request, _("Sale completed: Receipt %s") % sale.receipt_number)
        return redirect("pos:receipt", public_id=sale.public_id)
    except Exception as err:
        if not is_json:
            messages.error(request, str(err))
        return (
            JsonResponse({"success": False, "error": str(err)}, status=400)
            if is_json
            else redirect("pos:terminal")
        )


@permission_required("pos.access")
def receipt_view(request: HttpRequest, public_id: str) -> HttpResponse:
    """Printable POS receipt (80mm thermal CSS and PDF format)."""
    org = _get_org(request)
    sale = selectors.get_sale(organization=org, public_id=public_id)
    if not sale:
        raise PermissionDenied(_("Sale receipt not found."))

    invoice = sale.invoice
    lines = invoice.lines.select_related("product").all()
    payments = invoice.payments.all() if hasattr(invoice, "payments") else []

    is_raw = request.GET.get("raw") == "1" or request.GET.get("autoprint") == "1"
    layout_template = "layouts/base.html" if is_raw else "layouts/app.html"

    context = {
        "org": org,
        "sale": sale,
        "shift": sale.shift,
        "register": sale.register,
        "invoice": invoice,
        "lines": lines,
        "payments": payments,
        "is_raw": is_raw,
        "layout_template": layout_template,
    }
    response = render(request, "pos/receipt.html", context)

    # Allow same-origin framing so POS terminal iframe can trigger direct receipt print
    csp = dict(getattr(settings, "SECURE_CSP", {}))
    csp["frame-ancestors"] = ["'self'"]
    response._csp_config = csp
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


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


@permission_required("pos.access")
def hold_cart_action(request: HttpRequest) -> HttpResponse:
    """Park an active cart to be resumed later."""
    org = _get_org(request)
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
        shift = get_object_or_404(POSShift.all_tenants, pk=data["shift_id"], organization=org)
        if not check_object_scope(request.user, shift, organization=org):
            raise PermissionDenied(_("You do not have access to this shift."))
        held = services.hold_cart(
            organization=org,
            shift=shift,
            cart_data=data.get("cart_data", {}),
            cart_label=data.get("cart_label", "Customer 1"),
            total_amount=Decimal(str(data.get("total_amount", "0.0000"))),
            actor=request.user,
        )
        return JsonResponse({"success": True, "held_cart_id": held.pk})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@permission_required("pos.access")
def resume_cart_action(request: HttpRequest, held_cart_id: int) -> HttpResponse:
    """Retrieve and delete a held cart to restore onto checkout screen."""
    org = _get_org(request)
    try:
        cart_data = services.resume_cart(
            organization=org,
            held_cart_id=held_cart_id,
            actor=request.user,
        )
        return JsonResponse({"success": True, "cart": cart_data})
    except Exception as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)


@permission_required("pos.access")
def printers_view(request: HttpRequest) -> HttpResponse:
    """Return live system printers for POS terminal."""
    printers = selectors.get_system_printers()
    return JsonResponse({"printers": printers})


@permission_required("pos.access")
def test_printer_action(request: HttpRequest) -> HttpResponse:
    """Send a test print slip directly to the chosen OS hardware printer."""
    org = _get_org(request)
    printer_name = request.GET.get("printer_name") or request.POST.get("printer_name")
    if not printer_name and request.content_type == "application/json":
        with contextlib.suppress(Exception):
            printer_name = json.loads(request.body.decode("utf-8")).get("printer_name")

    if not printer_name:
        return JsonResponse({"success": False, "error": str(_("No printer specified."))}, status=400)

    threading.Thread(
        target=printing.spool_test_slip_to_printer,
        kwargs={"organization": org, "printer_name": printer_name},
        daemon=True,
    ).start()
    return JsonResponse({"success": True, "printer_name": printer_name})
