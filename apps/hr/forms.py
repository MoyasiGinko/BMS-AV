"""Django Forms for Human Resources administrative actions and self-service."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.hr.models import (
    AttendanceStatus,
    Employee,
    EmployeeDocument,
    EmployeeStatus,
    LeaveRequest,
    LeaveType,
    Position,
    Shift,
)
from apps.tenancy.models import Branch, Department, Organization

User = get_user_model()

INPUT_CSS = (
    "w-full rounded-lg border-slate-300 dark:border-slate-700 "
    "dark:bg-slate-800 dark:text-white px-3 py-2 text-sm"
)
MONO_INPUT_CSS = f"{INPUT_CSS} font-mono"
UPPER_MONO_CSS = f"{INPUT_CSS} uppercase font-mono"


class PositionForm(forms.ModelForm):
    class Meta:
        model = Position
        fields = [
            "title",
            "code",
            "department",
            "description",
            "min_salary",
            "max_salary",
            "is_active",
        ]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": INPUT_CSS,
                    "placeholder": "e.g. Senior Software Engineer",
                }
            ),
            "code": forms.TextInput(
                attrs={
                    "class": UPPER_MONO_CSS,
                    "placeholder": "e.g. ENG-SR-01",
                }
            ),
            "department": forms.Select(attrs={"class": INPUT_CSS}),
            "description": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 3}),
            "min_salary": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.01"}),
            "max_salary": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.01"}),
            "is_active": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["department"].queryset = Department.all_tenants.filter(
                organization=organization, is_active=True
            )


class EmployeeForm(forms.ModelForm):
    national_id = forms.CharField(
        label=_("National ID / SSN"),
        required=False,
        widget=forms.TextInput(attrs={"class": MONO_INPUT_CSS, "placeholder": "Encrypted at rest"}),
    )
    bank_account = forms.CharField(
        label=_("Bank Account / IBAN"),
        required=False,
        widget=forms.TextInput(attrs={"class": MONO_INPUT_CSS, "placeholder": "Encrypted at rest"}),
    )

    class Meta:
        model = Employee
        fields = [
            "code",
            "first_name",
            "last_name",
            "work_email",
            "personal_email",
            "phone",
            "position",
            "department",
            "branch",
            "user",
            "manager",
            "default_shift",
            "hire_date",
            "employment_type",
            "status",
            "date_of_birth",
            "gender",
            "emergency_contact_name",
            "emergency_contact_phone",
            "notes",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": UPPER_MONO_CSS, "placeholder": "EMP-0001"}),
            "first_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "last_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "work_email": forms.EmailInput(attrs={"class": INPUT_CSS}),
            "personal_email": forms.EmailInput(attrs={"class": INPUT_CSS}),
            "phone": forms.TextInput(attrs={"class": INPUT_CSS}),
            "position": forms.Select(attrs={"class": INPUT_CSS}),
            "department": forms.Select(attrs={"class": INPUT_CSS}),
            "branch": forms.Select(attrs={"class": INPUT_CSS}),
            "user": forms.Select(attrs={"class": INPUT_CSS}),
            "manager": forms.Select(attrs={"class": INPUT_CSS}),
            "default_shift": forms.Select(attrs={"class": INPUT_CSS}),
            "hire_date": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "employment_type": forms.Select(attrs={"class": INPUT_CSS}),
            "status": forms.Select(attrs={"class": INPUT_CSS}),
            "date_of_birth": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "gender": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "Optional"}),
            "emergency_contact_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "emergency_contact_phone": forms.TextInput(attrs={"class": INPUT_CSS}),
            "notes": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 3}),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["department"].queryset = Department.all_tenants.filter(
                organization=organization, is_active=True
            )
            self.fields["branch"].queryset = Branch.all_tenants.filter(
                organization=organization, is_active=True
            )
            self.fields["position"].queryset = Position.all_tenants.filter(
                organization=organization, is_active=True
            )
            self.fields["manager"].queryset = Employee.all_tenants.filter(
                organization=organization, status=EmployeeStatus.ACTIVE
            )
            self.fields["default_shift"].queryset = Shift.all_tenants.filter(
                organization=organization, is_active=True
            )
        if self.instance and self.instance.pk:
            self.fields["national_id"].initial = self.instance.national_id
            self.fields["bank_account"].initial = self.instance.bank_account


class EmployeeSelfServiceForm(forms.Form):
    personal_email = forms.EmailField(
        label=_("Personal Email"),
        required=False,
        widget=forms.EmailInput(attrs={"class": INPUT_CSS}),
    )
    phone = forms.CharField(
        label=_("Phone Number"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CSS}),
    )
    emergency_contact_name = forms.CharField(
        label=_("Emergency Contact Name"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CSS}),
    )
    emergency_contact_phone = forms.CharField(
        label=_("Emergency Contact Phone"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CSS}),
    )


class EmployeeDocumentForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocument
        fields = ["title", "document_type", "file", "expiry_date", "notes"]
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": INPUT_CSS,
                    "placeholder": "e.g. Passport Scan, Signed Offer Letter",
                }
            ),
            "document_type": forms.TextInput(
                attrs={
                    "class": INPUT_CSS,
                    "placeholder": "e.g. id_proof, contract, certificate",
                }
            ),
            "file": forms.FileInput(attrs={"class": INPUT_CSS}),
            "expiry_date": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "notes": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 2}),
        }


class EmployeeStatusTransitionForm(forms.Form):
    target_status = forms.ChoiceField(
        label=_("Target Status"),
        choices=EmployeeStatus.choices,
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    termination_date = forms.DateField(
        label=_("Effective / Termination Date"),
        required=False,
        widget=forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
    )
    reason = forms.CharField(
        label=_("Reason / Justification"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CSS,
                "rows": 2,
                "placeholder": "Reason for transition or termination notes",
            }
        ),
    )


class ShiftForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = [
            "name",
            "start_time",
            "end_time",
            "break_minutes",
            "is_overnight",
            "description",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "e.g. Standard 9-5"}),
            "start_time": forms.TimeInput(attrs={"class": INPUT_CSS, "type": "time"}),
            "end_time": forms.TimeInput(attrs={"class": INPUT_CSS, "type": "time"}),
            "break_minutes": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "5"}),
            "is_overnight": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
            "description": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 2}),
            "is_active": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
        }


class AttendanceCheckInForm(forms.Form):
    notes = forms.CharField(
        label=_("Check-in Notes"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "Optional location or note"}),
    )


class AttendanceCheckOutForm(forms.Form):
    notes = forms.CharField(
        label=_("Check-out Notes"),
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "Optional handoff or note"}),
    )


class AttendanceManualForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
    )
    check_in = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"class": INPUT_CSS, "type": "datetime-local"}),
    )
    check_out = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"class": INPUT_CSS, "type": "datetime-local"}),
    )
    status = forms.ChoiceField(
        choices=AttendanceStatus.choices,
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    shift = forms.ModelChoiceField(
        queryset=Shift.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": INPUT_CSS, "rows": 2}),
    )

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["employee"].queryset = Employee.all_tenants.filter(
                organization=organization, status=EmployeeStatus.ACTIVE
            )
            self.fields["shift"].queryset = Shift.all_tenants.filter(
                organization=organization, is_active=True
            )


class LeaveTypeForm(forms.ModelForm):
    class Meta:
        model = LeaveType
        fields = [
            "name",
            "code",
            "is_paid",
            "default_allowance_days",
            "requires_approval",
            "is_active",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "e.g. Annual Vacation"}),
            "code": forms.TextInput(attrs={"class": UPPER_MONO_CSS, "placeholder": "ANNUAL"}),
            "is_paid": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
            "default_allowance_days": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.5"}),
            "requires_approval": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
            "description": forms.Textarea(attrs={"class": INPUT_CSS, "rows": 2}),
        }


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = [
            "leave_type",
            "start_date",
            "end_date",
            "days_count",
            "reason",
        ]
        widgets = {
            "leave_type": forms.Select(attrs={"class": INPUT_CSS}),
            "start_date": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": INPUT_CSS, "type": "date"}),
            "days_count": forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.5"}),
            "reason": forms.Textarea(
                attrs={"class": INPUT_CSS, "rows": 3, "placeholder": "Reason for leave request"}
            ),
        }

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["leave_type"].queryset = LeaveType.all_tenants.filter(
                organization=organization, is_active=True
            )


class LeaveRequestReviewForm(forms.Form):
    rejection_reason = forms.CharField(
        label=_("Rejection Reason"),
        required=False,
        widget=forms.Textarea(
            attrs={"class": INPUT_CSS, "rows": 2, "placeholder": "Explain reason if rejecting"}
        ),
    )


class LeaveBalanceAllocateForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    leave_type = forms.ModelChoiceField(
        queryset=LeaveType.objects.none(),
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    year = forms.IntegerField(
        widget=forms.NumberInput(attrs={"class": MONO_INPUT_CSS}),
    )
    allocated_days = forms.DecimalField(
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": MONO_INPUT_CSS, "step": "0.5"}),
    )

    def __init__(self, *args: Any, organization: Organization | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if organization:
            self.fields["employee"].queryset = Employee.all_tenants.filter(
                organization=organization, status=EmployeeStatus.ACTIVE
            )
            self.fields["leave_type"].queryset = LeaveType.all_tenants.filter(
                organization=organization, is_active=True
            )
