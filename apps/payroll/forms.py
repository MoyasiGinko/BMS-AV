"""Django Forms for Payroll configuration, structure setup, assignments, and runs."""

from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.hr.models import Employee, EmployeeStatus
from apps.payroll.models import (
    EmployeeSalaryAssignment,
    PayrollRun,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureItem,
)
from apps.tenancy.models import Organization

INPUT_CSS = "w-full rounded-lg border-line bg-surface text-ink px-3 py-2 text-sm shadow-2xs"
MONO_INPUT_CSS = f"{INPUT_CSS} font-mono"
UPPER_MONO_CSS = f"{INPUT_CSS} uppercase font-mono"


class SalaryComponentForm(forms.ModelForm):
    class Meta:
        model = SalaryComponent
        fields = [
            "name",
            "code",
            "component_type",
            "is_taxable",
            "is_active",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "e.g. Basic Allowance"}),
            "code": forms.TextInput(attrs={"class": UPPER_MONO_CSS, "placeholder": "e.g. BASIC"}),
            "component_type": forms.Select(attrs={"class": INPUT_CSS}),
            "is_taxable": forms.CheckboxInput(attrs={"class": "rounded border-slate-300"}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded border-slate-300"}),
            "description": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 3}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        self.organization = organization
        super().__init__(*args, **kwargs)

    def clean_code(self) -> str:
        code = self.cleaned_data["code"].strip().upper()
        if self.organization:
            qs = SalaryComponent.all_tenants.filter(organization=self.organization, code=code)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(_("Salary component code must be unique per organization."))
        return code


class SalaryStructureForm(forms.ModelForm):
    class Meta:
        model = SalaryStructure
        fields = ["name", "code", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "e.g. Executive Package"}),
            "code": forms.TextInput(attrs={"class": UPPER_MONO_CSS, "placeholder": "e.g. EXEC-01"}),
            "description": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded border-slate-300"}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        self.organization = organization
        super().__init__(*args, **kwargs)

    def clean_code(self) -> str:
        code = self.cleaned_data["code"].strip().upper()
        if self.organization:
            qs = SalaryStructure.all_tenants.filter(organization=self.organization, code=code)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(_("Salary structure code must be unique per organization."))
        return code


class SalaryStructureItemForm(forms.ModelForm):
    class Meta:
        model = SalaryStructureItem
        fields = ["component", "calculation_type", "amount", "percentage"]
        widgets = {
            "component": forms.Select(attrs={"class": INPUT_CSS}),
            "calculation_type": forms.Select(attrs={"class": INPUT_CSS}),
            "amount": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.01"}),
            "percentage": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.01"}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["component"].queryset = SalaryComponent.all_tenants.filter(
                organization=organization, is_active=True
            )


class EmployeeSalaryAssignmentForm(forms.ModelForm):
    class Meta:
        model = EmployeeSalaryAssignment
        fields = [
            "employee",
            "salary_structure",
            "base_salary",
            "effective_from",
            "effective_to",
            "payment_method",
            "bank_name",
            "bank_account_number",
            "is_active",
        ]
        widgets = {
            "employee": forms.Select(attrs={"class": INPUT_CSS}),
            "salary_structure": forms.Select(attrs={"class": INPUT_CSS}),
            "base_salary": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.01"}),
            "effective_from": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "effective_to": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "payment_method": forms.Select(attrs={"class": INPUT_CSS}),
            "bank_account_number": forms.TextInput(
                attrs={"class": MONO_INPUT_CSS, "placeholder": "Account #"}
            ),
            "is_active": forms.CheckboxInput(attrs={"class": "rounded border-slate-300"}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["employee"].queryset = Employee.all_tenants.filter(
                organization=organization, status=EmployeeStatus.ACTIVE
            ).order_by("first_name", "last_name")
            self.fields["salary_structure"].queryset = SalaryStructure.all_tenants.filter(
                organization=organization, is_active=True
            ).order_by("name")


class PayrollRunForm(forms.ModelForm):
    class Meta:
        model = PayrollRun
        fields = ["period_start", "period_end", "payment_date", "notes"]
        widgets = {
            "period_start": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "period_end": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "payment_date": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "notes": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 3, "placeholder": "Notes or memo..."}),
        }

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        start = cleaned_data.get("period_start")
        end = cleaned_data.get("period_end")
        if start and end and end < start:
            raise forms.ValidationError(_("Period end date cannot precede period start date."))
        return cleaned_data


class PayrollPayForm(forms.Form):
    payment_account = forms.CharField(
        label=_("Disbursement Account / Mapping"),
        initial="bank",
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": "e.g. 'bank' or account code '1020'",
            }
        ),
        help_text=_("Account mapping key or code from which net salaries are disbursed."),
    )
