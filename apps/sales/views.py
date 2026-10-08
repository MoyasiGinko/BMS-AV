"""Views for the Sales and Invoicing module: Quotations, Orders, Invoices, and Credit Notes."""

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.catalog.models import Product
from apps.core.permissions import permission_required
from apps.sales import selectors, services
from apps.sales.exceptions import SalesError
from apps.sales.forms import (
    CreditNoteFilterForm,
    CreditNoteForm,
    InvoiceFilterForm,
    InvoiceForm,
    OrderFilterForm,
    QuoteFilterForm,
    QuoteForm,
    SalesOrderForm,
)
from apps.sales.models import CreditNote, Invoice, Quote, SalesOrder
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


# ============================================================================
# QUOTATIONS
# ============================================================================


@permission_required("sales.view")
def quote_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    filter_form = QuoteFilterForm(request.GET)
    status = request.GET.get("status") or None
    search = request.GET.get("search") or None

    quotes = selectors.list_quotes(organization=org, status=status, search=search)

    context = {
        "quotes": quotes,
        "filter_form": filter_form,
        "metrics": selectors.get_sales_summary_metrics(organization=org),
    }

    if getattr(request, "htmx", False):
        return render(request, "sales/partials/quote_table.html", context)
    return render(request, "sales/quote_list.html", context)


@permission_required("sales.view")
def quote_detail(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    quote = selectors.get_quote(organization=org, public_id=public_id)
    if not quote:
        messages.error(request, _("Quotation not found."))
        return redirect("sales:quote_list")

    return render(request, "sales/quote_detail.html", {"quote": quote})


@permission_required("sales.create")
def quote_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    products = Product.all_tenants.filter(organization=org, is_active=True)

    if request.method == "POST":
        form = QuoteForm(request.POST, organization=org)
        product_id = request.POST.get("product")
        quantity_str = request.POST.get("quantity", "1.0000")
        unit_price_str = request.POST.get("unit_price", "0.0000")
        discount_str = request.POST.get("discount_percent", "0.00")

        if form.is_valid() and product_id:
            try:
                product = get_object_or_404(Product.all_tenants, pk=product_id, organization=org)
                lines = [
                    {
                        "product": product,
                        "quantity": Decimal(quantity_str),
                        "unit_price": Decimal(unit_price_str) or product.price,
                        "discount_percent": Decimal(discount_str),
                        "tax_rate": product.tax_code.rate if product.tax_code else Decimal("0.00"),
                    }
                ]
                quote = services.create_quote(
                    organization=org,
                    customer=form.cleaned_data["customer"],
                    branch=form.cleaned_data.get("branch"),
                    warehouse=form.cleaned_data.get("warehouse"),
                    lines=lines,
                    date=form.cleaned_data.get("date"),
                    valid_until=form.cleaned_data.get("valid_until"),
                    currency=form.cleaned_data.get("currency") or "USD",
                    notes=form.cleaned_data.get("notes", ""),
                    terms=form.cleaned_data.get("terms", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Quotation %(num)s created successfully.") % {"num": quote.quote_number},
                )
                return redirect("sales:quote_detail", public_id=quote.public_id)
            except SalesError as err:
                messages.error(request, str(err))
    else:
        form = QuoteForm(organization=org)

    return render(request, "sales/quote_form.html", {"form": form, "products": products})


@permission_required("sales.update")
def quote_accept(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    quote = get_object_or_404(Quote.all_tenants, public_id=public_id, organization=org)
    try:
        services.accept_quote(organization=org, quote=quote, actor=request.user)
        messages.success(request, _("Quotation %(num)s accepted.") % {"num": quote.quote_number})
    except SalesError as err:
        messages.error(request, str(err))
    return redirect("sales:quote_detail", public_id=quote.public_id)


@permission_required("sales.create")
def quote_convert(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    quote = get_object_or_404(Quote.all_tenants, public_id=public_id, organization=org)
    try:
        order = services.convert_quote_to_order(organization=org, quote=quote, actor=request.user)
        messages.success(
            request,
            _("Quotation %(num)s converted to Sales Order %(ord)s.")
            % {"num": quote.quote_number, "ord": order.order_number},
        )
        return redirect("sales:order_detail", public_id=order.public_id)
    except SalesError as err:
        messages.error(request, str(err))
        return redirect("sales:quote_detail", public_id=quote.public_id)


@permission_required("sales.view")
def quote_print(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)
    quote = selectors.get_quote(organization=org, public_id=public_id)
    if not quote:
        return redirect("sales:quote_list")
    return render(request, "sales/quote_print.html", {"quote": quote, "org": org})


# ============================================================================
# SALES ORDERS
# ============================================================================


@permission_required("sales.view")
def order_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    filter_form = OrderFilterForm(request.GET)
    status = request.GET.get("status") or None
    search = request.GET.get("search") or None

    orders = selectors.list_orders(organization=org, status=status, search=search)

    context = {
        "orders": orders,
        "filter_form": filter_form,
        "metrics": selectors.get_sales_summary_metrics(organization=org),
    }

    if getattr(request, "htmx", False):
        return render(request, "sales/partials/order_table.html", context)
    return render(request, "sales/order_list.html", context)


@permission_required("sales.view")
def order_detail(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    order = selectors.get_order(organization=org, public_id=public_id)
    if not order:
        messages.error(request, _("Sales order not found."))
        return redirect("sales:order_list")

    return render(request, "sales/order_detail.html", {"order": order})


@permission_required("sales.create")
def order_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    products = Product.all_tenants.filter(organization=org, is_active=True)

    if request.method == "POST":
        form = SalesOrderForm(request.POST, organization=org)
        product_id = request.POST.get("product")
        quantity_str = request.POST.get("quantity", "1.0000")
        unit_price_str = request.POST.get("unit_price", "0.0000")
        discount_str = request.POST.get("discount_percent", "0.00")

        if form.is_valid() and product_id:
            try:
                product = get_object_or_404(Product.all_tenants, pk=product_id, organization=org)
                lines = [
                    {
                        "product": product,
                        "quantity": Decimal(quantity_str),
                        "unit_price": Decimal(unit_price_str) or product.price,
                        "discount_percent": Decimal(discount_str),
                        "tax_rate": product.tax_code.rate if product.tax_code else Decimal("0.00"),
                    }
                ]
                order = services.create_sales_order(
                    organization=org,
                    customer=form.cleaned_data["customer"],
                    warehouse=form.cleaned_data["warehouse"],
                    branch=form.cleaned_data.get("branch"),
                    lines=lines,
                    order_date=form.cleaned_data.get("order_date"),
                    expected_delivery=form.cleaned_data.get("expected_delivery"),
                    currency=form.cleaned_data.get("currency") or "USD",
                    notes=form.cleaned_data.get("notes", ""),
                    terms=form.cleaned_data.get("terms", ""),
                    actor=request.user,
                )
                messages.success(request, _("Sales Order %(num)s created.") % {"num": order.order_number})
                return redirect("sales:order_detail", public_id=order.public_id)
            except SalesError as err:
                messages.error(request, str(err))
    else:
        form = SalesOrderForm(organization=org)

    return render(request, "sales/order_form.html", {"form": form, "products": products})


@permission_required("sales.confirm")
def order_confirm(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    order = get_object_or_404(SalesOrder.all_tenants, public_id=public_id, organization=org)
    try:
        services.confirm_sales_order(organization=org, order=order, actor=request.user)
        messages.success(request, _("Order %(num)s confirmed.") % {"num": order.order_number})
    except SalesError as err:
        messages.error(request, str(err))
    return redirect("sales:order_detail", public_id=order.public_id)


@permission_required("sales.update")
def order_cancel(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    order = get_object_or_404(SalesOrder.all_tenants, public_id=public_id, organization=org)
    try:
        services.cancel_sales_order(organization=org, order=order, actor=request.user)
        messages.success(request, _("Order %(num)s cancelled.") % {"num": order.order_number})
    except SalesError as err:
        messages.error(request, str(err))
    return redirect("sales:order_detail", public_id=order.public_id)


@permission_required("sales.create")
def order_convert_to_invoice(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    order = get_object_or_404(SalesOrder.all_tenants, public_id=public_id, organization=org)
    try:
        invoice = services.convert_order_to_invoice(organization=org, order=order, actor=request.user)
        messages.success(
            request,
            _("Sales Order %(ord)s converted to Invoice %(inv)s.")
            % {"ord": order.order_number, "inv": invoice.invoice_number},
        )
        return redirect("sales:invoice_detail", public_id=invoice.public_id)
    except SalesError as err:
        messages.error(request, str(err))
        return redirect("sales:order_detail", public_id=order.public_id)


# ============================================================================
# SALES INVOICES
# ============================================================================


@permission_required("sales.view")
def invoice_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    filter_form = InvoiceFilterForm(request.GET)
    status = request.GET.get("status") or None
    search = request.GET.get("search") or None
    is_overdue = request.GET.get("overdue") == "1"

    invoices = selectors.list_invoices(
        organization=org,
        status=status,
        search=search,
        is_overdue=is_overdue if is_overdue else None,
    )

    context = {
        "invoices": invoices,
        "filter_form": filter_form,
        "metrics": selectors.get_sales_summary_metrics(organization=org),
    }

    if getattr(request, "htmx", False):
        return render(request, "sales/partials/invoice_table.html", context)
    return render(request, "sales/invoice_list.html", context)


@permission_required("sales.view")
def invoice_detail(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    invoice = selectors.get_invoice(organization=org, public_id=public_id)
    if not invoice:
        messages.error(request, _("Invoice not found."))
        return redirect("sales:invoice_list")

    return render(request, "sales/invoice_detail.html", {"invoice": invoice})


@permission_required("sales.create")
def invoice_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    products = Product.all_tenants.filter(organization=org, is_active=True)

    if request.method == "POST":
        form = InvoiceForm(request.POST, organization=org)
        product_id = request.POST.get("product")
        quantity_str = request.POST.get("quantity", "1.0000")
        unit_price_str = request.POST.get("unit_price", "0.0000")
        discount_str = request.POST.get("discount_percent", "0.00")

        if form.is_valid() and product_id:
            try:
                product = get_object_or_404(Product.all_tenants, pk=product_id, organization=org)
                lines = [
                    {
                        "product": product,
                        "quantity": Decimal(quantity_str),
                        "unit_price": Decimal(unit_price_str) or product.price,
                        "discount_percent": Decimal(discount_str),
                        "tax_rate": product.tax_code.rate if product.tax_code else Decimal("0.00"),
                    }
                ]
                invoice = services.create_invoice(
                    organization=org,
                    customer=form.cleaned_data["customer"],
                    warehouse=form.cleaned_data["warehouse"],
                    branch=form.cleaned_data.get("branch"),
                    lines=lines,
                    invoice_date=form.cleaned_data.get("invoice_date"),
                    due_date=form.cleaned_data.get("due_date"),
                    currency=form.cleaned_data.get("currency") or "USD",
                    notes=form.cleaned_data.get("notes", ""),
                    terms=form.cleaned_data.get("terms", ""),
                    actor=request.user,
                )
                messages.success(request, _("Invoice %(num)s created.") % {"num": invoice.invoice_number})
                return redirect("sales:invoice_detail", public_id=invoice.public_id)
            except SalesError as err:
                messages.error(request, str(err))
    else:
        form = InvoiceForm(organization=org)

    return render(request, "sales/invoice_form.html", {"form": form, "products": products})


@permission_required("sales.confirm")
def invoice_post(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    invoice = get_object_or_404(Invoice.all_tenants, public_id=public_id, organization=org)
    try:
        services.post_invoice(organization=org, invoice=invoice, actor=request.user)
        messages.success(
            request,
            _("Invoice %(num)s posted to general ledger and stock issued.") % {"num": invoice.invoice_number},
        )
    except SalesError as err:
        messages.error(request, str(err))
    return redirect("sales:invoice_detail", public_id=invoice.public_id)


@permission_required("sales.void")
def invoice_void(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    invoice = get_object_or_404(Invoice.all_tenants, public_id=public_id, organization=org)
    reason = request.POST.get("reason", "Cancelled by user")
    try:
        services.void_invoice(organization=org, invoice=invoice, actor=request.user, reason=reason)
        messages.success(
            request,
            _("Invoice %(num)s voided and entries reversed.") % {"num": invoice.invoice_number},
        )
    except SalesError as err:
        messages.error(request, str(err))
    return redirect("sales:invoice_detail", public_id=invoice.public_id)


@permission_required("sales.view")
def invoice_print(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)
    invoice = selectors.get_invoice(organization=org, public_id=public_id)
    if not invoice:
        return redirect("sales:invoice_list")
    return render(request, "sales/invoice_print.html", {"invoice": invoice, "org": org})


# ============================================================================
# CREDIT NOTES
# ============================================================================


@permission_required("sales.view")
def credit_note_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    filter_form = CreditNoteFilterForm(request.GET)
    status = request.GET.get("status") or None
    search = request.GET.get("search") or None

    credit_notes = selectors.list_credit_notes(organization=org, status=status, search=search)

    context = {
        "credit_notes": credit_notes,
        "filter_form": filter_form,
        "metrics": selectors.get_sales_summary_metrics(organization=org),
    }

    if getattr(request, "htmx", False):
        return render(request, "sales/partials/credit_note_table.html", context)
    return render(request, "sales/credit_note_list.html", context)


@permission_required("sales.view")
def credit_note_detail(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    credit_note = selectors.get_credit_note(organization=org, public_id=public_id)
    if not credit_note:
        messages.error(request, _("Credit note not found."))
        return redirect("sales:credit_note_list")

    return render(request, "sales/credit_note_detail.html", {"credit_note": credit_note})


@permission_required("sales.create")
def credit_note_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)

    products = Product.all_tenants.filter(organization=org, is_active=True)

    if request.method == "POST":
        form = CreditNoteForm(request.POST, organization=org)
        product_id = request.POST.get("product")
        quantity_str = request.POST.get("quantity", "1.0000")
        unit_price_str = request.POST.get("unit_price", "0.0000")
        restock = request.POST.get("restock") == "1"

        if form.is_valid() and product_id:
            try:
                product = get_object_or_404(Product.all_tenants, pk=product_id, organization=org)
                lines = [
                    {
                        "product": product,
                        "quantity": Decimal(quantity_str),
                        "unit_price": Decimal(unit_price_str) or product.price,
                        "tax_rate": product.tax_code.rate if product.tax_code else Decimal("0.00"),
                        "restock": restock,
                        "unit_cost": product.cost,
                    }
                ]
                credit_note = services.create_credit_note(
                    organization=org,
                    customer=form.cleaned_data["customer"],
                    warehouse=form.cleaned_data["warehouse"],
                    branch=form.cleaned_data.get("branch"),
                    lines=lines,
                    credit_note_date=form.cleaned_data.get("credit_note_date"),
                    currency=form.cleaned_data.get("currency") or "USD",
                    reason=form.cleaned_data.get("reason", ""),
                    notes=form.cleaned_data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Credit Note %(num)s created.") % {"num": credit_note.credit_note_number},
                )
                return redirect("sales:credit_note_detail", public_id=credit_note.public_id)
            except SalesError as err:
                messages.error(request, str(err))
    else:
        form = CreditNoteForm(organization=org)

    return render(request, "sales/credit_note_form.html", {"form": form, "products": products})


@permission_required("sales.create")
def credit_note_from_invoice(request: HttpRequest, invoice_public_id: str) -> HttpResponse:
    org = _get_org(request)

    invoice = get_object_or_404(Invoice.all_tenants, public_id=invoice_public_id, organization=org)
    try:
        credit_note = services.create_credit_note_from_invoice(
            organization=org,
            invoice=invoice,
            reason=_("Credit generated from %(inv)s") % {"inv": invoice.invoice_number},
            actor=request.user,
        )
        messages.success(
            request,
            _("Credit Note %(num)s generated from Invoice %(inv)s.")
            % {"num": credit_note.credit_note_number, "inv": invoice.invoice_number},
        )
        return redirect("sales:credit_note_detail", public_id=credit_note.public_id)
    except SalesError as err:
        messages.error(request, str(err))
        return redirect("sales:invoice_detail", public_id=invoice.public_id)


@permission_required("sales.confirm")
def credit_note_post(request: HttpRequest, public_id: str) -> HttpResponse:
    org = _get_org(request)

    credit_note = get_object_or_404(CreditNote.all_tenants, public_id=public_id, organization=org)
    try:
        services.post_credit_note(organization=org, credit_note=credit_note, actor=request.user)
        messages.success(
            request,
            _("Credit Note %(num)s posted to general ledger.") % {"num": credit_note.credit_note_number},
        )
    except SalesError as err:
        messages.error(request, str(err))
    return redirect("sales:credit_note_detail", public_id=credit_note.public_id)
