"""Forms for customer accounts, addresses, contacts, manual adjustments, and statements."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import PriceList
from apps.customers.models import (
    Customer,
    CustomerAddress,
    CustomerContact,
    CustomerStatus,
    CustomerType,
)
from apps.tenancy.models import Organization


class CustomerFilterForm(forms.Form):
    """Filter form for customer list view."""

    query = forms.CharField(
        label=_("Search"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-input text-sm py-1.5",
                "placeholder": _("Search by name, code, phone, email..."),
            }
        ),
    )
    status = forms.ChoiceField(
        label=_("Status"),
        required=False,
        choices=[("", _("All Statuses")), *list(CustomerStatus.choices)],
        widget=forms.Select(attrs={"class": "form-select text-sm py-1.5"}),
    )
    type = forms.ChoiceField(
        label=_("Type"),
        required=False,
        choices=[("", _("All Types")), *list(CustomerType.choices)],
        widget=forms.Select(attrs={"class": "form-select text-sm py-1.5"}),
    )
    has_balance_only = forms.BooleanField(
        label=_("With Balance Only"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox rounded"}),
    )
    over_credit_only = forms.BooleanField(
        label=_("Over Credit Limit"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox rounded"}),
    )


class CustomerForm(forms.ModelForm):
    """Customer creation and edit form."""

    opening_balance = forms.DecimalField(
        label=_("Opening AR Balance (Debit)"),
        max_digits=18,
        decimal_places=4,
        required=False,
        initial=Decimal("0.0000"),
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
        help_text=_("Initial balance receivable at the time of migration. Recorded as opening entry."),
    )

    class Meta:
        model = Customer
        fields = [
            "name",
            "code",
            "type",
            "status",
            "email",
            "phone",
            "tax_id",
            "currency",
            "price_list",
            "credit_limit",
            "payment_terms_days",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input", "placeholder": _("e.g. Acme Corp")}),
            "code": forms.TextInput(
                attrs={"class": "form-input", "placeholder": _("Leave blank to auto-generate")}
            ),
            "type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "email": forms.EmailInput(attrs={"class": "form-input", "placeholder": "billing@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-input", "placeholder": "+1 555-0100"}),
            "tax_id": forms.TextInput(attrs={"class": "form-input", "placeholder": "VAT / Tax ID"}),
            "currency": forms.TextInput(attrs={"class": "form-input", "maxlength": "3"}),
            "price_list": forms.Select(attrs={"class": "form-select"}),
            "credit_limit": forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
            "payment_terms_days": forms.NumberInput(attrs={"class": "form-input", "min": "0"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 3}),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["code"].required = False
        pl_qs = PriceList.objects.filter(organization=organization, is_active=True).order_by("name")
        cast(forms.ModelChoiceField, self.fields["price_list"]).queryset = pl_qs
        cast(forms.ModelChoiceField, self.fields["price_list"]).empty_label = _(
            "Standard Pricing (No Override)"
        )

        if self.instance and self.instance.pk:
            self.fields.pop("opening_balance", None)


class CustomerAddressForm(forms.ModelForm):
    """Customer address form."""

    class Meta:
        model = CustomerAddress
        fields = [
            "type",
            "recipient_name",
            "line1",
            "line2",
            "city",
            "state_or_province",
            "postal_code",
            "country",
            "phone",
            "is_default",
        ]
        widgets = {
            "type": forms.Select(attrs={"class": "form-select"}),
            "recipient_name": forms.TextInput(attrs={"class": "form-input"}),
            "line1": forms.TextInput(attrs={"class": "form-input"}),
            "line2": forms.TextInput(attrs={"class": "form-input"}),
            "city": forms.TextInput(attrs={"class": "form-input"}),
            "state_or_province": forms.TextInput(attrs={"class": "form-input"}),
            "postal_code": forms.TextInput(attrs={"class": "form-input"}),
            "country": forms.TextInput(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input"}),
            "is_default": forms.CheckboxInput(attrs={"class": "form-checkbox rounded"}),
        }


class CustomerContactForm(forms.ModelForm):
    """Customer individual contact form."""

    class Meta:
        model = CustomerContact
        fields = [
            "first_name",
            "last_name",
            "title",
            "email",
            "phone",
            "is_primary",
            "notes",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-input"}),
            "last_name": forms.TextInput(attrs={"class": "form-input"}),
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "email": forms.EmailInput(attrs={"class": "form-input"}),
            "phone": forms.TextInput(attrs={"class": "form-input"}),
            "is_primary": forms.CheckboxInput(attrs={"class": "form-checkbox rounded"}),
            "notes": forms.Textarea(attrs={"class": "form-textarea", "rows": 2}),
        }


class CustomerAdjustmentForm(forms.Form):
    """Manual AR balance adjustment form."""

    ADJUSTMENT_TYPE_CHOICES = [
        ("debit", _("Debit (Increase balance / additional charge)")),
        ("credit", _("Credit (Decrease balance / discount / write-off)")),
    ]

    adjustment_type = forms.ChoiceField(
        label=_("Adjustment Type"),
        choices=ADJUSTMENT_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    amount = forms.DecimalField(
        label=_("Adjustment Amount"),
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    reference_number = forms.CharField(
        label=_("Document / Reference #"),
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "ADJ-2026-001"}),
    )
    reason = forms.CharField(
        label=_("Justification / Reason"),
        widget=forms.Textarea(
            attrs={"class": "form-textarea", "rows": 3, "placeholder": _("Explain why...")}
        ),
    )


class CustomerStatementFilterForm(forms.Form):
    """Statement date range filter form."""

    start_date = forms.DateField(
        label=_("Start Date"),
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )
    end_date = forms.DateField(
        label=_("End Date"),
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        first_of_month = today.replace(day=1)
        self.fields["start_date"].initial = first_of_month
        self.fields["end_date"].initial = today
