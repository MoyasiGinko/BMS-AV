"""Forms for full Accounting module: Chart of Accounts, Journals, Banking, Expenses, FX, Tax."""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, cast

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import (
    Account,
    AccountType,
    BankAccount,
    BankTransactionType,
    ExpenseCategory,
    ExpensePaymentMethod,
    ExpenseStatus,
    JournalEntry,
)
from apps.tenancy.models import Organization


class AccountForm(forms.ModelForm):
    """Form to create or update an Account in Chart of Accounts."""

    class Meta:
        model = Account
        fields = [
            "code",
            "name",
            "type",
            "parent",
            "currency",
            "is_control",
            "is_active",
            "description",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "e.g. 1050"}),
            "name": forms.TextInput(attrs={"placeholder": "e.g. Petty Cash"}),
            "type": forms.Select(),
            "currency": forms.TextInput(attrs={"placeholder": "USD"}),
            "description": forms.TextInput(attrs={"placeholder": "Account purpose"}),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        parent_field = cast(forms.ModelChoiceField, self.fields["parent"])
        parent_field.queryset = Account.all_tenants.filter(organization=organization, is_active=True)
        parent_field.required = False
        parent_field.empty_label = _("-- Top Level Account --")


class AccountFilterForm(forms.Form):
    type = forms.ChoiceField(
        choices=[("", _("All Types")), *list(AccountType.choices)],
        required=False,
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Search by code or name...")}),
    )


class ManualJournalFilterForm(forms.Form):
    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(JournalEntry.STATUS_CHOICES)],
        required=False,
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class ManualJournalForm(forms.Form):
    date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Entry Date"),
    )
    memo = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": _("Description of manual journal...")}),
        label=_("Memo / Narration"),
    )


class BankAccountForm(forms.ModelForm):
    opening_balance = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        initial=Decimal("0.0000"),
        required=False,
        label=_("Opening Balance"),
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )

    class Meta:
        model = BankAccount
        fields = [
            "name",
            "account_number",
            "bank_name",
            "routing_number",
            "swift_bic",
            "currency",
            "gl_account",
            "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Primary Operating Account"}),
            "account_number": forms.TextInput(attrs={"placeholder": "Account or IBAN number"}),
            "bank_name": forms.TextInput(attrs={"placeholder": "e.g. JPMorgan Chase"}),
            "routing_number": forms.TextInput(attrs={"placeholder": "Routing / Sort code"}),
            "swift_bic": forms.TextInput(attrs={"placeholder": "SWIFT / BIC"}),
            "currency": forms.TextInput(attrs={"placeholder": "USD"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        gl_field = cast(forms.ModelChoiceField, self.fields["gl_account"])
        gl_field.queryset = Account.all_tenants.filter(
            organization=organization,
            type=AccountType.ASSET,
            is_active=True,
        )


class BankTransactionForm(forms.Form):
    date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
    )
    transaction_type = forms.ChoiceField(choices=BankTransactionType.choices)
    reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Check or wire ref")}),
    )
    payee = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Payee / Payer")}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Transaction notes")}),
    )


class BankReconciliationForm(forms.Form):
    statement_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Statement Cut-off Date"),
    )
    statement_ending_balance = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
        label=_("Statement Ending Balance"),
    )


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "code", "gl_account", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g. Office Supplies"}),
            "code": forms.TextInput(attrs={"placeholder": "OFFICE"}),
            "description": forms.TextInput(attrs={"placeholder": "Category description"}),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        gl_field = cast(forms.ModelChoiceField, self.fields["gl_account"])
        gl_field.queryset = Account.all_tenants.filter(
            organization=organization,
            type=AccountType.EXPENSE,
            is_active=True,
        )


class ExpenseFilterForm(forms.Form):
    category = forms.ChoiceField(required=False)
    status = forms.ChoiceField(
        choices=[("", _("All Statuses")), *list(ExpenseStatus.choices)],
        required=False,
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cats = [("", _("All Categories"))] + [
            (str(c.pk), c.name)
            for c in ExpenseCategory.all_tenants.filter(organization=organization, is_active=True)
        ]
        cast(forms.ChoiceField, self.fields["category"]).choices = cats


class ExpenseForm(forms.Form):
    category = forms.ModelChoiceField(
        queryset=ExpenseCategory.objects.none(),
        label=_("Expense Category"),
    )
    paid_from_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        label=_("Paid From (GL Account)"),
    )
    bank_account = forms.ModelChoiceField(
        queryset=BankAccount.objects.none(),
        required=False,
        label=_("Linked Bank Account (Optional)"),
        empty_label=_("-- None / Direct Cash --"),
    )
    date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Expense Date"),
    )
    amount = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
        label=_("Net Amount"),
    )
    tax_rate = forms.DecimalField(
        max_digits=6,
        decimal_places=4,
        initial=Decimal("0.0000"),
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
        label=_("Tax Rate (e.g. 0.05 for 5%)"),
    )
    currency = forms.CharField(
        max_length=3,
        initial="USD",
        label=_("Currency"),
    )
    exchange_rate = forms.DecimalField(
        max_digits=18,
        decimal_places=6,
        initial=Decimal("1.000000"),
        required=False,
        widget=forms.NumberInput(attrs={"step": "0.000001"}),
        label=_("Exchange Rate"),
    )
    payment_method = forms.ChoiceField(
        choices=ExpensePaymentMethod.choices,
        label=_("Payment Method"),
    )
    vendor_name = forms.CharField(
        max_length=128,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Vendor or payee name")}),
        label=_("Vendor / Payee"),
    )
    reference = forms.CharField(
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Invoice / Receipt #")}),
        label=_("Reference"),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": _("Expense description...")}),
        label=_("Notes"),
    )
    receipt = forms.FileField(
        required=False,
        label=_("Receipt Upload"),
    )

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ModelChoiceField, self.fields["category"]).queryset = ExpenseCategory.all_tenants.filter(
            organization=organization, is_active=True
        )
        cast(forms.ModelChoiceField, self.fields["paid_from_account"]).queryset = Account.all_tenants.filter(
            organization=organization,
            type__in=[AccountType.ASSET, AccountType.LIABILITY],
            is_active=True,
        )
        cast(forms.ModelChoiceField, self.fields["bank_account"]).queryset = BankAccount.all_tenants.filter(
            organization=organization, is_active=True
        )


class ExchangeRateForm(forms.Form):
    from_currency = forms.CharField(
        max_length=3,
        widget=forms.TextInput(attrs={"placeholder": "EUR"}),
        label=_("From Currency"),
    )
    to_currency = forms.CharField(
        max_length=3,
        widget=forms.TextInput(attrs={"placeholder": "USD"}),
        label=_("To Currency"),
    )
    rate = forms.DecimalField(
        max_digits=18,
        decimal_places=6,
        widget=forms.NumberInput(attrs={"step": "0.000001", "placeholder": "1.085000"}),
        label=_("Exchange Rate"),
    )
    effective_date = forms.DateField(
        initial=timezone.now,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Effective Date"),
    )
    source = forms.CharField(
        max_length=64,
        initial="manual",
        required=False,
        label=_("Source"),
    )


class TaxSummaryFilterForm(forms.Form):
    period_start = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Period Start"),
    )
    period_end = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Period End"),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        today = datetime.date.today()
        if "period_start" not in self.initial:
            self.initial["period_start"] = today.replace(day=1)
        if "period_end" not in self.initial:
            self.initial["period_end"] = today
