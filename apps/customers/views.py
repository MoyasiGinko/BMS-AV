"""Customer management views: customer list, detail, statement,
address/contact management, and adjustments.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.permissions import permission_required
from apps.customers import selectors, services
from apps.customers.exceptions import CreditLimitExceeded, CustomerError, CustomerHasTransactions
from apps.customers.forms import (
    CustomerAddressForm,
    CustomerAdjustmentForm,
    CustomerContactForm,
    CustomerFilterForm,
    CustomerForm,
    CustomerStatementFilterForm,
)
from apps.customers.models import Customer, CustomerAddress, CustomerContact
from apps.tenancy.models import Organization


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


@permission_required("customers.view")
def customer_list(request: HttpRequest) -> HttpResponse:
    """Customer accounts list with metrics cards, filters, and HTMX partial swap."""
    org = _get_org(request)
    form = CustomerFilterForm(request.GET)

    query = request.GET.get("query", "")
    status = request.GET.get("status", "")
    cust_type = request.GET.get("type", "")
    has_balance_only = request.GET.get("has_balance_only") == "on"
    over_credit_only = request.GET.get("over_credit_only") == "on"
    order_by = request.GET.get("order_by", "name")

    qs = selectors.get_customers(
        organization=org,
        query=query,
        status=status,
        type=cust_type,
        has_balance_only=has_balance_only,
        over_credit_only=over_credit_only,
        order_by=order_by,
    )

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    metrics = selectors.get_customer_overview_metrics(organization=org)

    context = {
        "page_obj": page_obj,
        "form": form,
        "metrics": metrics,
        "query": query,
        "status": status,
        "type": cust_type,
        "order_by": order_by,
        "has_balance_only": has_balance_only,
        "over_credit_only": over_credit_only,
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "customers/partials/customer_table.html", context)

    return render(request, "customers/customer_list.html", context)


@permission_required("customers.create")
def customer_create(request: HttpRequest) -> HttpResponse:
    """Create a new customer account."""
    org = _get_org(request)

    if request.method == "POST":
        form = CustomerForm(request.POST, organization=org)
        if form.is_valid():
            data = form.cleaned_data
            opening_bal = data.pop("opening_balance", Decimal("0.0000")) or Decimal("0.0000")
            try:
                cust = services.create_customer(
                    organization=org,
                    name=data["name"],
                    code=data.get("code") or None,
                    type=data["type"],
                    status=data["status"],
                    email=data.get("email", ""),
                    phone=data.get("phone", ""),
                    tax_id=data.get("tax_id", ""),
                    currency=data.get("currency", "USD"),
                    price_list=data.get("price_list"),
                    credit_limit=data.get("credit_limit") or Decimal("0.0000"),
                    payment_terms_days=data.get("payment_terms_days") or 0,
                    opening_balance=opening_bal,
                    notes=data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(
                    request, _("Customer '%(name)s' created successfully.") % {"name": cust.name}
                )
                return redirect("customers:customer_detail", customer_id=cust.pk)
            except CustomerError as err:
                messages.error(request, str(err))
    else:
        form = CustomerForm(organization=org)

    return render(request, "customers/customer_form.html", {"form": form, "is_new": True})


@permission_required("customers.view")
def customer_detail(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Customer account detail view with tabs for overview, ledger, statements, addresses, and contacts."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    tab = request.GET.get("tab", "overview")

    # Ledger
    ledger_entries = selectors.get_customer_balance_ledger(organization=org, customer=customer)
    paginator = Paginator(ledger_entries, 20)
    page_number = request.GET.get("page", 1)
    ledger_page = paginator.get_page(page_number)

    # Statement Filter
    today = timezone.localdate()
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    try:
        start_date = datetime.date.fromisoformat(start_date_str) if start_date_str else today.replace(day=1)
    except ValueError, TypeError:
        start_date = today.replace(day=1)

    try:
        end_date = datetime.date.fromisoformat(end_date_str) if end_date_str else today
    except ValueError, TypeError:
        end_date = today

    statement_form = CustomerStatementFilterForm(initial={"start_date": start_date, "end_date": end_date})
    statement_data = selectors.get_customer_statement(
        organization=org,
        customer=customer,
        start_date=start_date,
        end_date=end_date,
    )

    addresses = customer.addresses.all().order_by("-is_default", "type")
    contacts = customer.contacts.all().order_by("-is_primary", "first_name")

    adj_form = CustomerAdjustmentForm()
    addr_form = CustomerAddressForm()
    contact_form = CustomerContactForm()

    context = {
        "customer": customer,
        "tab": tab,
        "ledger_page": ledger_page,
        "statement_data": statement_data,
        "statement_form": statement_form,
        "addresses": addresses,
        "contacts": contacts,
        "adj_form": adj_form,
        "addr_form": addr_form,
        "contact_form": contact_form,
        "start_date": start_date,
        "end_date": end_date,
    }
    return render(request, "customers/customer_detail.html", context)


@permission_required("customers.update")
def customer_update(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Edit customer profile and credit terms."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer, organization=org)
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.update_customer(
                    organization=org,
                    customer=customer,
                    name=data["name"],
                    type=data["type"],
                    status=data["status"],
                    email=data.get("email", ""),
                    phone=data.get("phone", ""),
                    tax_id=data.get("tax_id", ""),
                    currency=data.get("currency", "USD"),
                    price_list=data.get("price_list"),
                    credit_limit=data.get("credit_limit") or Decimal("0.0000"),
                    payment_terms_days=data.get("payment_terms_days") or 0,
                    notes=data.get("notes", ""),
                    actor=request.user,
                )
                messages.success(request, _("Customer updated successfully."))
                return redirect("customers:customer_detail", customer_id=customer.pk)
            except CustomerError as err:
                messages.error(request, str(err))
    else:
        form = CustomerForm(instance=customer, organization=org)

    return render(
        request, "customers/customer_form.html", {"form": form, "customer": customer, "is_new": False}
    )


@permission_required("customers.delete")
def customer_delete(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Delete a customer if no ledger transactions exist."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    if request.method == "POST":
        try:
            services.delete_customer(organization=org, customer=customer, actor=request.user)
            messages.success(request, _("Customer deleted successfully."))
            return redirect("customers:customer_list")
        except CustomerHasTransactions as err:
            messages.error(request, str(err))
            return redirect("customers:customer_detail", customer_id=customer.pk)

    return render(request, "customers/customer_confirm_delete.html", {"customer": customer})


@permission_required("customers.adjust_balance")
def customer_adjust_balance(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Manual debit or credit adjustment to customer AR subledger."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    if request.method == "POST":
        form = CustomerAdjustmentForm(request.POST)
        if form.is_valid():
            try:
                entry = services.adjust_customer_balance(
                    organization=org,
                    customer=customer,
                    adjustment_type=form.cleaned_data["adjustment_type"],
                    amount=form.cleaned_data["amount"],
                    reason=form.cleaned_data["reason"],
                    reference_number=form.cleaned_data.get("reference_number", ""),
                    actor=request.user,
                )
                messages.success(
                    request,
                    _("Balance adjustment of %(amount)s recorded. New balance: %(bal)s")
                    % {"amount": entry.debit or entry.credit, "bal": entry.balance_after},
                )
            except (CustomerError, CreditLimitExceeded) as err:
                messages.error(request, str(err))
    return redirect("customers:customer_detail", customer_id=customer.pk)


@permission_required("customers.update")
def customer_address_create(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Add a structured address to a customer."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    if request.method == "POST":
        form = CustomerAddressForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.add_customer_address(
                organization=org,
                customer=customer,
                type=data["type"],
                recipient_name=data.get("recipient_name", ""),
                line1=data["line1"],
                line2=data.get("line2", ""),
                city=data["city"],
                state_or_province=data.get("state_or_province", ""),
                postal_code=data.get("postal_code", ""),
                country=data.get("country", "US"),
                phone=data.get("phone", ""),
                is_default=data.get("is_default", False),
                actor=request.user,
            )
            messages.success(request, _("Address added successfully."))
    return redirect(f"{redirect('customers:customer_detail', customer_id=customer.pk).url}?tab=addresses")


@permission_required("customers.update")
def customer_address_delete(request: HttpRequest, customer_id: int, address_id: int) -> HttpResponse:
    """Remove a customer address."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)
    addr = get_object_or_404(CustomerAddress.all_tenants, organization=org, customer=customer, pk=address_id)

    if request.method == "POST":
        addr.delete()
        messages.success(request, _("Address removed."))
    return redirect(f"{redirect('customers:customer_detail', customer_id=customer.pk).url}?tab=addresses")


@permission_required("customers.update")
def customer_contact_create(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Add an individual contact person to a customer."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    if request.method == "POST":
        form = CustomerContactForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            services.add_customer_contact(
                organization=org,
                customer=customer,
                first_name=data["first_name"],
                last_name=data.get("last_name", ""),
                title=data.get("title", ""),
                email=data.get("email", ""),
                phone=data.get("phone", ""),
                is_primary=data.get("is_primary", False),
                notes=data.get("notes", ""),
                actor=request.user,
            )
            messages.success(request, _("Contact added successfully."))
    return redirect(f"{redirect('customers:customer_detail', customer_id=customer.pk).url}?tab=contacts")


@permission_required("customers.update")
def customer_contact_delete(request: HttpRequest, customer_id: int, contact_id: int) -> HttpResponse:
    """Remove a customer contact."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)
    contact = get_object_or_404(
        CustomerContact.all_tenants, organization=org, customer=customer, pk=contact_id
    )

    if request.method == "POST":
        contact.delete()
        messages.success(request, _("Contact removed."))
    return redirect(f"{redirect('customers:customer_detail', customer_id=customer.pk).url}?tab=contacts")


@permission_required("customers.view")
def customer_statement_print(request: HttpRequest, customer_id: int) -> HttpResponse:
    """Printable / full-page statement view for a customer."""
    org = _get_org(request)
    customer = get_object_or_404(Customer.all_tenants, organization=org, pk=customer_id)

    today = timezone.localdate()
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    try:
        start_date = datetime.date.fromisoformat(start_date_str) if start_date_str else today.replace(day=1)
    except ValueError, TypeError:
        start_date = today.replace(day=1)

    try:
        end_date = datetime.date.fromisoformat(end_date_str) if end_date_str else today
    except ValueError, TypeError:
        end_date = today

    statement_data = selectors.get_customer_statement(
        organization=org,
        customer=customer,
        start_date=start_date,
        end_date=end_date,
    )

    context = {
        "customer": customer,
        "statement_data": statement_data,
        "start_date": start_date,
        "end_date": end_date,
        "now": timezone.now(),
    }
    return render(request, "customers/customer_statement_print.html", context)
