from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.customers.models import Customer
from apps.sales.models import (
    CreditNote,
    CreditNoteStatus,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentRefund,
    PaymentReminderRule,
    PaymentStatus,
    Quote,
    QuoteStatus,
    RecurringInvoiceProfile,
    RecurringProfileStatus,
    SalesOrder,
    SalesOrderStatus,
)
from apps.tenancy.models import Branch, Organization, Warehouse


class QuoteFilterForm(forms.Form):
    """Filter form for quotations list."""

    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(QuoteStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search quotes..."),
                "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600",
            }
        ),
    )


class OrderFilterForm(forms.Form):
    """Filter form for sales orders list."""

    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(SalesOrderStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search orders..."),
                "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600",
            }
        ),
    )


class InvoiceFilterForm(forms.Form):
    """Filter form for sales invoices list."""

    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(InvoiceStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search invoices..."),
                "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600",
            }
        ),
    )


class CreditNoteFilterForm(forms.Form):
    """Filter form for credit notes list."""

    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(CreditNoteStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search credit notes..."),
                "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600",
            }
        ),
    )


def _scope_choice_field(field: forms.Field, queryset: Any) -> None:
    if isinstance(field, forms.ModelChoiceField):
        field.queryset = queryset


class QuoteForm(forms.ModelForm):
    """Creation / editing form for Quotes."""

    class Meta:
        model = Quote
        fields = [
            "customer",
            "branch",
            "date",
            "valid_until",
            "currency",
            "notes",
            "terms",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "terms": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "currency" in self.fields:
            self.fields["currency"].required = False
        if organization:
            if "customer" in self.fields:
                _scope_choice_field(
                    self.fields["customer"], Customer.all_tenants.filter(organization=organization)
                )
            if "branch" in self.fields:
                _scope_choice_field(
                    self.fields["branch"], Branch.all_tenants.filter(organization=organization)
                )


class SalesOrderForm(forms.ModelForm):
    """Creation / editing form for Sales Orders."""

    class Meta:
        model = SalesOrder
        fields = [
            "customer",
            "warehouse",
            "branch",
            "order_date",
            "expected_delivery",
            "currency",
            "notes",
            "terms",
        ]
        widgets = {
            "order_date": forms.DateInput(attrs={"type": "date"}),
            "expected_delivery": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "terms": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "currency" in self.fields:
            self.fields["currency"].required = False
        if organization:
            if "customer" in self.fields:
                _scope_choice_field(
                    self.fields["customer"], Customer.all_tenants.filter(organization=organization)
                )
            if "branch" in self.fields:
                _scope_choice_field(
                    self.fields["branch"], Branch.all_tenants.filter(organization=organization)
                )
            if "warehouse" in self.fields:
                _scope_choice_field(
                    self.fields["warehouse"], Warehouse.all_tenants.filter(organization=organization)
                )


class InvoiceForm(forms.ModelForm):
    """Creation / editing form for Sales Invoices."""

    class Meta:
        model = Invoice
        fields = [
            "customer",
            "warehouse",
            "branch",
            "invoice_date",
            "due_date",
            "currency",
            "notes",
            "terms",
        ]
        widgets = {
            "invoice_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "terms": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "currency" in self.fields:
            self.fields["currency"].required = False
        if organization:
            if "customer" in self.fields:
                _scope_choice_field(
                    self.fields["customer"], Customer.all_tenants.filter(organization=organization)
                )
            if "branch" in self.fields:
                _scope_choice_field(
                    self.fields["branch"], Branch.all_tenants.filter(organization=organization)
                )
            if "warehouse" in self.fields:
                _scope_choice_field(
                    self.fields["warehouse"], Warehouse.all_tenants.filter(organization=organization)
                )


class CreditNoteForm(forms.ModelForm):
    """Creation / editing form for Credit Notes."""

    class Meta:
        model = CreditNote
        fields = [
            "customer",
            "warehouse",
            "branch",
            "credit_note_date",
            "currency",
            "reason",
            "notes",
        ]
        widgets = {
            "credit_note_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.TextInput(attrs={"placeholder": _("e.g. Damaged goods returned")}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "currency" in self.fields:
            self.fields["currency"].required = False
        if organization:
            if "customer" in self.fields:
                _scope_choice_field(
                    self.fields["customer"], Customer.all_tenants.filter(organization=organization)
                )
            if "branch" in self.fields:
                _scope_choice_field(
                    self.fields["branch"], Branch.all_tenants.filter(organization=organization)
                )
            if "warehouse" in self.fields:
                _scope_choice_field(
                    self.fields["warehouse"], Warehouse.all_tenants.filter(organization=organization)
                )


class PaymentFilterForm(forms.Form):
    """Filter form for customer payments list."""

    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(PaymentStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    payment_method = forms.ChoiceField(
        choices=[("", _("All Methods")), *list(PaymentMethod.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search payment #, customer, reference..."),
                "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600 w-64",
            }
        ),
    )


class PaymentForm(forms.ModelForm):
    """Creation form for recording customer payments."""

    class Meta:
        model = Payment
        fields = [
            "customer",
            "amount",
            "payment_method",
            "payment_date",
            "currency",
            "reference",
            "branch",
            "notes",
        ]
        widgets = {
            "payment_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "reference": forms.TextInput(attrs={"placeholder": _("e.g. Check #, Transfer Ref")}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "currency" in self.fields:
            self.fields["currency"].required = False
        if organization:
            if "customer" in self.fields:
                _scope_choice_field(
                    self.fields["customer"], Customer.all_tenants.filter(organization=organization)
                )
            if "branch" in self.fields:
                _scope_choice_field(
                    self.fields["branch"], Branch.all_tenants.filter(organization=organization)
                )


class PaymentRefundForm(forms.ModelForm):
    """Creation form for customer refunds."""

    class Meta:
        model = PaymentRefund
        fields = [
            "amount",
            "refund_date",
            "reason",
        ]
        widgets = {
            "refund_date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "reason": forms.Textarea(attrs={"rows": 2, "placeholder": _("Reason for refund...")}),
        }


class RecurringProfileFilterForm(forms.Form):
    """Filter form for recurring invoice profiles list."""

    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(RecurringProfileStatus.choices)],
        required=False,
        widget=forms.Select(
            attrs={"class": "form-select text-sm rounded-lg border-slate-300 dark:border-slate-600"}
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": _("Search profiles..."),
                "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600",
            }
        ),
    )


class RecurringInvoiceProfileForm(forms.ModelForm):
    """Creation and editing form for recurring invoice profiles."""

    class Meta:
        model = RecurringInvoiceProfile
        fields = [
            "title",
            "customer",
            "warehouse",
            "branch",
            "frequency",
            "interval",
            "start_date",
            "end_date",
            "payment_terms_days",
            "currency",
            "auto_post",
            "send_email",
            "total_cycles_limit",
            "notes",
            "terms",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "terms": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if "currency" in self.fields:
            self.fields["currency"].required = False
        if organization:
            if "customer" in self.fields:
                _scope_choice_field(
                    self.fields["customer"], Customer.all_tenants.filter(organization=organization)
                )
            if "branch" in self.fields:
                _scope_choice_field(
                    self.fields["branch"], Branch.all_tenants.filter(organization=organization)
                )
            if "warehouse" in self.fields:
                _scope_choice_field(
                    self.fields["warehouse"], Warehouse.all_tenants.filter(organization=organization)
                )


class PaymentReminderRuleForm(forms.ModelForm):
    """Creation and editing form for payment reminder timing rules."""

    class Meta:
        model = PaymentReminderRule
        fields = [
            "name",
            "timing_days",
            "is_active",
            "subject_template",
            "body_template",
        ]
        widgets = {
            "timing_days": forms.NumberInput(
                attrs={
                    "class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600",
                    "placeholder": "-3 for 3d before due, 7 for 7d overdue",
                }
            ),
            "subject_template": forms.TextInput(
                attrs={"class": "form-input text-sm rounded-lg border-slate-300 dark:border-slate-600"}
            ),
            "body_template": forms.Textarea(
                attrs={
                    "rows": 4,
                    "class": "form-textarea text-sm rounded-lg border-slate-300 dark:border-slate-600",
                }
            ),
        }
