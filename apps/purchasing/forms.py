"""Forms for the Purchasing module: Suppliers, POs, Goods Receipts, Bills, Payments."""

from __future__ import annotations

from typing import Any, cast

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import scope_queryset
from apps.purchasing.models import (
    PurchaseOrderStatus,
    Supplier,
    SupplierBillStatus,
    SupplierPaymentMethod,
)
from apps.tenancy.models import Branch, Organization, Warehouse


class SupplierFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search suppliers by name or code..."),
                "class": "neu-input form-input text-sm rounded-xl",
            }
        ),
    )
    is_active = forms.ChoiceField(
        choices=[("", _("All")), ("1", _("Active")), ("0", _("Inactive"))],
        required=False,
        widget=forms.Select(
            attrs={"class": "neu-select form-select text-sm rounded-xl"}
        ),
    )


class SupplierForm(forms.ModelForm):
    code = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. SUP-0001"}),
    )
    currency = forms.CharField(
        initial="USD",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "USD"}),
    )

    class Meta:
        model = Supplier
        fields = [
            "code",
            "name",
            "contact_person",
            "email",
            "phone",
            "address",
            "city",
            "country",
            "postal_code",
            "tax_id",
            "currency",
            "payment_terms_days",
            "is_active",
            "notes",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. SUP-0001"}),
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": "Acme Supplier Inc."}),
            "contact_person": forms.TextInput(attrs={"class": "form-input"}),
            "email": forms.EmailInput(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input"}),
            "address": forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
            "city": forms.TextInput(attrs={"class": "form-input"}),
            "country": forms.TextInput(attrs={"class": "form-input"}),
            "postal_code": forms.TextInput(attrs={"class": "form-input"}),
            "tax_id": forms.TextInput(attrs={"class": "form-input"}),
            "currency": forms.TextInput(attrs={"class": "form-input", "maxlength": 3}),
            "payment_terms_days": forms.NumberInput(attrs={"class": "form-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-checkbox"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
        }


class PurchaseOrderFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(PurchaseOrderStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "neu-select form-select text-sm rounded-xl"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search POs..."),
                "class": "neu-input form-input text-sm rounded-xl",
            }
        ),
    )


class PurchaseOrderForm(forms.Form):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Supplier"),
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Branch"),
    )
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Receiving Warehouse"),
    )
    order_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
        label=_("Order Date"),
    )
    expected_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
        label=_("Expected Date"),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-textarea"}),
        label=_("Notes"),
    )
    terms = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-textarea"}),
        label=_("Terms & Conditions"),
    )

    def __init__(self, *args: Any, organization: Organization, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ModelChoiceField, self.fields["supplier"]).queryset = Supplier.all_tenants.filter(
            organization=organization, is_active=True
        )
        branches = Branch.all_tenants.filter(organization=organization)
        warehouses = Warehouse.all_tenants.filter(organization=organization)
        if user is not None:
            branches = scope_queryset(branches, user, organization=organization)
            warehouses = scope_queryset(warehouses, user, organization=organization)

        cast(forms.ModelChoiceField, self.fields["branch"]).queryset = branches
        cast(forms.ModelChoiceField, self.fields["warehouse"]).queryset = warehouses


class SupplierBillFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(SupplierBillStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "neu-select form-select text-sm rounded-xl"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search bills..."),
                "class": "neu-input form-input text-sm rounded-xl",
            }
        ),
    )


class SupplierPaymentForm(forms.Form):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Supplier"),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=0.0001,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
        label=_("Payment Amount"),
    )
    payment_method = forms.ChoiceField(
        choices=SupplierPaymentMethod.choices,
        initial=SupplierPaymentMethod.BANK_TRANSFER,
        widget=forms.Select(attrs={"class": "form-select"}),
        label=_("Payment Method"),
    )
    payment_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
        label=_("Payment Date"),
    )
    reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "Check # / Wire Ref"}),
        label=_("Reference"),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-textarea"}),
        label=_("Notes"),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ModelChoiceField, self.fields["supplier"]).queryset = Supplier.all_tenants.filter(
            organization=organization, is_active=True
        )
