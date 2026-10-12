"""Forms for Point of Sale (POS) operations."""

from decimal import Decimal
from typing import Any

from django import forms

from apps.core.permissions import scope_queryset
from apps.pos.models import POSRegister
from apps.tenancy.models import Branch, Organization, Warehouse

_INPUT_CSS = (
    "w-full text-sm rounded-lg border-slate-300 dark:border-slate-700 "
    "bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
)
_MONO_INPUT_CSS = f"{_INPUT_CSS} font-mono"
_BOLD_MONO_INPUT_CSS = f"{_MONO_INPUT_CSS} font-bold"


def _scope_choice_field(field: forms.Field, queryset: Any) -> None:
    if isinstance(field, forms.ModelChoiceField):
        field.queryset = queryset


class POSRegisterForm(forms.ModelForm):
    class Meta:
        model = POSRegister
        fields = ["code", "name", "branch", "warehouse", "receipt_header", "receipt_footer", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": _MONO_INPUT_CSS}),
            "name": forms.TextInput(attrs={"class": _INPUT_CSS}),
            "branch": forms.Select(attrs={"class": _INPUT_CSS}),
            "warehouse": forms.Select(attrs={"class": _INPUT_CSS}),
            "receipt_header": forms.Textarea(attrs={"rows": 2, "class": _INPUT_CSS}),
            "receipt_footer": forms.Textarea(attrs={"rows": 2, "class": _INPUT_CSS}),
            "is_active": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        _scope_choice_field(self.fields["branch"], Branch.all_tenants.filter(organization=organization))
        _scope_choice_field(self.fields["warehouse"], Warehouse.all_tenants.filter(organization=organization))


class POSOpenShiftForm(forms.Form):
    register = forms.ModelChoiceField(
        queryset=POSRegister.objects.none(),
        widget=forms.Select(attrs={"class": _INPUT_CSS}),
    )
    opening_cash = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        initial=Decimal("0.00"),
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "class": _MONO_INPUT_CSS}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": _INPUT_CSS}),
    )

    def __init__(self, *args: Any, organization: Organization, user: Any = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        registers = POSRegister.all_tenants.filter(organization=organization, is_active=True)
        if user is not None:
            registers = scope_queryset(registers, user, organization=organization)
        _scope_choice_field(
            self.fields["register"],
            registers,
        )


class POSCloseShiftForm(forms.Form):
    closing_cash_counted = forms.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "class": _BOLD_MONO_INPUT_CSS}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": _INPUT_CSS}),
    )
