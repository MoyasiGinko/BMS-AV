"""Views for the Purchasing module: Suppliers, POs, Goods Receipts, Bills, Payments, and Returns."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.catalog.models import Product
from apps.core.permissions import check_object_scope, permission_required, scope_queryset
from apps.purchasing import selectors, services
from apps.purchasing.forms import (
    PurchaseOrderFilterForm,
    PurchaseOrderForm,
    SupplierBillFilterForm,
    SupplierFilterForm,
    SupplierForm,
    SupplierPaymentForm,
)
from apps.purchasing.models import (
    GoodsReceipt,
    PurchaseOrder,
    PurchaseReturn,
    Supplier,
    SupplierBill,
)
from apps.tenancy.models import Organization, Warehouse


def _get_org(request: HttpRequest) -> Organization:
    org: Organization | None = getattr(request, "organization", None)
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


# =============================================================================
# 1. SUPPLIERS
# =============================================================================


@permission_required("purchasing.view")
def supplier_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = SupplierFilterForm(request.GET)
    search = request.GET.get("search") or None
    is_active_val = request.GET.get("is_active")
    is_active = bool(int(is_active_val)) if is_active_val in ("0", "1") else None

    suppliers = selectors.list_suppliers(organization=org, is_active=is_active, search=search)
    summary = selectors.get_purchasing_summary(organization=org)

    context = {
        "suppliers": suppliers,
        "filter_form": form,
        "summary": summary,
    }
    if getattr(request, "htmx", False):
        return render(request, "purchasing/partials/supplier_table.html", context)
    return render(request, "purchasing/supplier_list.html", context)


@permission_required("purchasing.view")
def supplier_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    supplier = get_object_or_404(Supplier.all_tenants, pk=pk, organization=org)
    pos = selectors.list_purchase_orders(organization=org, supplier_id=supplier.pk)[:5]
    bills = selectors.list_supplier_bills(organization=org, supplier_id=supplier.pk)[:5]
    payments = selectors.list_supplier_payments(organization=org, supplier_id=supplier.pk)[:5]

    return render(
        request,
        "purchasing/supplier_detail.html",
        {
            "supplier": supplier,
            "purchase_orders": pos,
            "bills": bills,
            "payments": payments,
        },
    )


@permission_required("purchasing.create")
def supplier_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            supplier = services.create_supplier(
                organization=org,
                name=data["name"],
                code=data.get("code") or None,
                contact_person=data.get("contact_person", ""),
                email=data.get("email", ""),
                phone=data.get("phone", ""),
                address=data.get("address", ""),
                city=data.get("city", ""),
                country=data.get("country", ""),
                postal_code=data.get("postal_code", ""),
                tax_id=data.get("tax_id", ""),
                currency=data.get("currency", "USD"),
                payment_terms_days=data.get("payment_terms_days", 30),
                notes=data.get("notes", ""),
                actor=request.user,
            )
            messages.success(request, _("Supplier %(name)s created successfully.") % {"name": supplier.name})
            return redirect("purchasing:supplier_detail", pk=supplier.pk)
    else:
        form = SupplierForm()

    return render(request, "purchasing/supplier_form.html", {"form": form, "title": _("New Supplier")})


@permission_required("purchasing.update")
def supplier_update(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    supplier = get_object_or_404(Supplier.all_tenants, pk=pk, organization=org)

    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            data = form.cleaned_data
            services.update_supplier(
                organization=org,
                supplier=supplier,
                name=data["name"],
                contact_person=data.get("contact_person"),
                email=data.get("email"),
                phone=data.get("phone"),
                address=data.get("address"),
                city=data.get("city"),
                country=data.get("country"),
                postal_code=data.get("postal_code"),
                tax_id=data.get("tax_id"),
                payment_terms_days=data.get("payment_terms_days"),
                is_active=data.get("is_active"),
                notes=data.get("notes"),
                actor=request.user,
            )
            messages.success(request, _("Supplier updated successfully."))
            return redirect("purchasing:supplier_detail", pk=supplier.pk)
    else:
        form = SupplierForm(instance=supplier)

    return render(
        request,
        "purchasing/supplier_form.html",
        {"form": form, "title": _("Edit Supplier %(name)s") % {"name": supplier.name}},
    )


# =============================================================================
# 2. PURCHASE ORDERS
# =============================================================================


@permission_required("purchasing.view")
def purchase_order_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = PurchaseOrderFilterForm(request.GET)
    status = request.GET.get("status") or None
    orders = selectors.list_purchase_orders(organization=org, status=status)
    orders = scope_queryset(orders, request.user, organization=org)

    context = {
        "orders": orders,
        "filter_form": form,
    }
    if getattr(request, "htmx", False):
        return render(request, "purchasing/partials/po_table.html", context)
    return render(request, "purchasing/purchase_order_list.html", context)


@permission_required("purchasing.view")
def purchase_order_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    po = selectors.get_purchase_order(organization=org, order_id=pk)
    if not po or not check_object_scope(request.user, po, organization=org):
        raise PermissionDenied(_("Purchase order not found."))

    return render(request, "purchasing/purchase_order_detail.html", {"po": po})


@permission_required("purchasing.create")
def purchase_order_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    products = Product.all_tenants.filter(organization=org, is_active=True).order_by("name")

    if request.method == "POST":
        form = PurchaseOrderForm(request.POST, organization=org, user=request.user)
        if form.is_valid():
            supplier = form.cleaned_data["supplier"]
            branch = form.cleaned_data.get("branch")
            warehouse = form.cleaned_data.get("warehouse")
            order_date = form.cleaned_data.get("order_date")
            expected_date = form.cleaned_data.get("expected_date")
            notes = form.cleaned_data.get("notes", "")
            terms = form.cleaned_data.get("terms", "")

            # Parse lines from POST
            product_ids = request.POST.getlist("product_id[]")
            quantities = request.POST.getlist("quantity[]")
            unit_prices = request.POST.getlist("unit_price[]")
            tax_rates = request.POST.getlist("tax_rate[]")

            lines = []
            for p_id, q_val, p_val, t_val in zip(
                product_ids, quantities, unit_prices, tax_rates, strict=False
            ):
                if not p_id or not q_val:
                    continue
                prod = Product.all_tenants.get(pk=int(p_id), organization=org)
                lines.append(
                    {
                        "product": prod,
                        "quantity": Decimal(q_val),
                        "unit_price": Decimal(p_val),
                        "tax_rate": Decimal(t_val) if t_val else Decimal("0.00"),
                    }
                )

            if not lines:
                messages.error(request, _("Please provide at least one product line."))
            else:
                po = services.create_purchase_order(
                    organization=org,
                    supplier=supplier,
                    branch=branch,
                    warehouse=warehouse,
                    order_date=order_date,
                    expected_date=expected_date,
                    lines=lines,
                    notes=notes,
                    terms=terms,
                    actor=request.user,
                )
                messages.success(request, _("Purchase order %(num)s created.") % {"num": po.order_number})
                return redirect("purchasing:purchase_order_detail", pk=po.pk)
    else:
        form = PurchaseOrderForm(organization=org, user=request.user)

    return render(
        request,
        "purchasing/purchase_order_form.html",
        {"form": form, "products": products, "title": _("New Purchase Order")},
    )


@permission_required("purchasing.approve")
def purchase_order_approve(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    po = get_object_or_404(PurchaseOrder.all_tenants, pk=pk, organization=org)
    if not check_object_scope(request.user, po, organization=org):
        raise PermissionDenied(_("Purchase order not found."))
    if request.method == "POST":
        try:
            services.approve_purchase_order(organization=org, purchase_order=po, actor=request.user)
            messages.success(request, _("Purchase order %(num)s approved.") % {"num": po.order_number})
        except ValidationError as err:
            messages.error(request, str(err))
    return redirect("purchasing:purchase_order_detail", pk=po.pk)


@permission_required("purchasing.update")
def purchase_order_cancel(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    po = get_object_or_404(PurchaseOrder.all_tenants, pk=pk, organization=org)
    if not check_object_scope(request.user, po, organization=org):
        raise PermissionDenied(_("Purchase order not found."))
    if request.method == "POST":
        try:
            services.cancel_purchase_order(organization=org, purchase_order=po, actor=request.user)
            messages.warning(request, _("Purchase order %(num)s cancelled.") % {"num": po.order_number})
        except ValidationError as err:
            messages.error(request, str(err))
    return redirect("purchasing:purchase_order_detail", pk=po.pk)


# =============================================================================
# 3. GOODS RECEIPTS
# =============================================================================


@permission_required("purchasing.view")
def goods_receipt_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    receipts = selectors.list_goods_receipts(organization=org)
    receipts = scope_queryset(receipts, request.user, organization=org)
    return render(request, "purchasing/goods_receipt_list.html", {"receipts": receipts})


@permission_required("purchasing.view")
def goods_receipt_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    receipt = selectors.get_goods_receipt(organization=org, receipt_id=pk)
    if not receipt or not check_object_scope(request.user, receipt, organization=org):
        raise PermissionDenied(_("Goods receipt not found."))
    return render(request, "purchasing/goods_receipt_detail.html", {"receipt": receipt})


@permission_required("purchasing.receive")
def goods_receipt_receive(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    receipt = get_object_or_404(GoodsReceipt.all_tenants, pk=pk, organization=org)
    if not check_object_scope(request.user, receipt, organization=org):
        raise PermissionDenied(_("Goods receipt not found."))
    if request.method == "POST":
        try:
            services.receive_goods_receipt(organization=org, goods_receipt=receipt, actor=request.user)
            msg = _("Stock issued into warehouse successfully for receipt %(num)s.") % {
                "num": receipt.receipt_number
            }
            messages.success(request, msg)
        except ValidationError as err:
            messages.error(request, str(err))
    return redirect("purchasing:goods_receipt_detail", pk=receipt.pk)


# =============================================================================
# 4. SUPPLIER BILLS
# =============================================================================


@permission_required("purchasing.view")
def supplier_bill_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    form = SupplierBillFilterForm(request.GET)
    status = request.GET.get("status") or None
    bills = selectors.list_supplier_bills(organization=org, status=status)
    bills = scope_queryset(bills, request.user, organization=org)

    context = {
        "bills": bills,
        "filter_form": form,
    }
    if getattr(request, "htmx", False):
        return render(request, "purchasing/partials/bill_table.html", context)
    return render(request, "purchasing/bill_list.html", context)


@permission_required("purchasing.view")
def supplier_bill_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    bill = selectors.get_supplier_bill(organization=org, bill_id=pk)
    if not bill or not check_object_scope(request.user, bill, organization=org):
        raise PermissionDenied(_("Supplier bill not found."))
    return render(request, "purchasing/bill_detail.html", {"bill": bill})


@permission_required("purchasing.post")
def supplier_bill_post(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    bill = get_object_or_404(SupplierBill.all_tenants, pk=pk, organization=org)
    if not check_object_scope(request.user, bill, organization=org):
        raise PermissionDenied(_("Supplier bill not found."))
    if request.method == "POST":
        try:
            services.post_supplier_bill(organization=org, bill=bill, actor=request.user)
            msg = _("Bill %(num)s posted to general ledger.") % {"num": bill.bill_number}
            messages.success(request, msg)
        except ValidationError as err:
            messages.error(request, str(err))
    return redirect("purchasing:supplier_bill_detail", pk=bill.pk)


@permission_required("purchasing.post")
def supplier_bill_void(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    bill = get_object_or_404(SupplierBill.all_tenants, pk=pk, organization=org)
    if not check_object_scope(request.user, bill, organization=org):
        raise PermissionDenied(_("Supplier bill not found."))
    if request.method == "POST":
        try:
            services.void_supplier_bill(organization=org, bill=bill, actor=request.user)
            msg = _("Bill %(num)s voided and ledger reversed.") % {"num": bill.bill_number}
            messages.warning(request, msg)
        except ValidationError as err:
            messages.error(request, str(err))
    return redirect("purchasing:supplier_bill_detail", pk=bill.pk)


# =============================================================================
# 5. SUPPLIER PAYMENTS
# =============================================================================


@permission_required("purchasing.view")
def supplier_payment_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    payments = selectors.list_supplier_payments(organization=org)
    return render(request, "purchasing/payment_list.html", {"payments": payments})


@permission_required("purchasing.view")
def supplier_payment_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    payment = selectors.get_supplier_payment(organization=org, payment_id=pk)
    if not payment:
        raise PermissionDenied(_("Payment not found."))
    return render(request, "purchasing/payment_detail.html", {"payment": payment})


@permission_required("purchasing.payment")
def supplier_payment_create(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    suppliers = Supplier.all_tenants.filter(organization=org, is_active=True).order_by("name")

    if request.method == "POST":
        form = SupplierPaymentForm(request.POST, organization=org)
        if form.is_valid():
            supplier = form.cleaned_data["supplier"]
            amount = form.cleaned_data["amount"]
            method = form.cleaned_data["payment_method"]
            pay_date = form.cleaned_data["payment_date"]
            reference = form.cleaned_data.get("reference", "")
            notes = form.cleaned_data.get("notes", "")

            # Check for bill allocation in POST
            allocations = []
            bill_id = request.POST.get("bill_id")
            if bill_id:
                allocations.append({"bill_id": int(bill_id), "amount": amount})

            try:
                payment = services.record_supplier_payment(
                    organization=org,
                    supplier=supplier,
                    amount=amount,
                    payment_method=method,
                    payment_date=pay_date,
                    reference=reference,
                    allocations=allocations,
                    notes=notes,
                    actor=request.user,
                )
                messages.success(request, _("Payment %(num)s recorded.") % {"num": payment.payment_number})
                return redirect("purchasing:supplier_payment_detail", pk=payment.pk)
            except ValidationError as err:
                messages.error(request, str(err))
    else:
        initial = {}
        if "supplier_id" in request.GET:
            initial["supplier"] = request.GET["supplier_id"]
        form = SupplierPaymentForm(organization=org, initial=initial)

    return render(
        request,
        "purchasing/payment_form.html",
        {"form": form, "suppliers": suppliers, "title": _("Record Supplier Payment")},
    )


# =============================================================================
# 6. PURCHASE RETURNS
# =============================================================================


@permission_required("purchasing.view")
def purchase_return_list(request: HttpRequest) -> HttpResponse:
    org = _get_org(request)
    returns = selectors.list_purchase_returns(organization=org)
    returns = scope_queryset(returns, request.user, organization=org)
    return render(request, "purchasing/return_list.html", {"returns": returns})


@permission_required("purchasing.view")
def purchase_return_detail(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    ret = selectors.get_purchase_return(organization=org, return_id=pk)
    if not ret or not check_object_scope(request.user, ret, organization=org):
        raise PermissionDenied(_("Purchase return not found."))
    return render(request, "purchasing/return_detail.html", {"purchase_return": ret})


@permission_required("purchasing.post")
def purchase_return_post(request: HttpRequest, pk: int) -> HttpResponse:
    org = _get_org(request)
    ret = get_object_or_404(PurchaseReturn.all_tenants, pk=pk, organization=org)
    if not check_object_scope(request.user, ret, organization=org):
        raise PermissionDenied(_("Purchase return not found."))
    if request.method == "POST":
        try:
            services.post_purchase_return(organization=org, purchase_return=ret, actor=request.user)
            messages.success(
                request, _("Purchase return %(num)s posted to ledger.") % {"num": ret.return_number}
            )
        except ValidationError as err:
            messages.error(request, str(err))
    return redirect("purchasing:purchase_return_detail", pk=ret.pk)


@permission_required("purchasing.create")
def purchase_orders_from_reorder(request: HttpRequest) -> HttpResponse:
    """Generate draft purchase orders grouped by supplier from reorder suggestions."""
    org = _get_org(request)
    if request.method == "POST":
        wh_val = request.POST.get("warehouse_id")
        wh_id = int(wh_val) if wh_val and wh_val.isdigit() else None
        warehouse = Warehouse.objects.filter(organization=org, pk=wh_id).first() if wh_id else None
        supp_val = request.POST.get("supplier_id")
        supp_id = int(supp_val) if supp_val and supp_val.isdigit() else None
        try:
            pos = services.create_purchase_orders_from_reorder_suggestions(
                organization=org,
                warehouse=warehouse,
                default_supplier_id=supp_id,
                actor=request.user,
            )
            if pos:
                messages.success(
                    request,
                    _("Created %(count)d draft purchase order(s) from low-stock suggestions.")
                    % {"count": len(pos)},
                )
            else:
                messages.info(request, _("No purchase orders were needed or generated."))
        except Exception as err:
            messages.error(request, str(err))
    return redirect("purchasing:purchase_order_list")
