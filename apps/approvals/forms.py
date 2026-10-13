"""Forms for the Approvals engine: rule configuration and decision handling."""

from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.approvals.models import (
    ApprovalRule,
    ApprovalRuleType,
    ApprovalStatus,
)
from apps.tenancy.models import Membership, Organization, Role

_INPUT_CLS = (
    "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 "
    "text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500"
)
_MONO_INPUT_CLS = f"{_INPUT_CLS} font-mono"
_FILTER_INPUT_CLS = (
    "rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 "
    "text-slate-900 dark:text-white text-sm px-3 py-1.5 focus:ring-2 focus:ring-primary-500"
)


class ApprovalRuleForm(forms.ModelForm):
    """Form to create or update an ApprovalRule."""

    class Meta:
        model = ApprovalRule
        fields = [
            "name",
            "rule_type",
            "description",
            "min_amount",
            "min_discount_percent",
            "approver_role",
            "approver_user",
            "sort_order",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": _INPUT_CLS,
                    "placeholder": _("e.g. Purchase Order over $5,000"),
                }
            ),
            "rule_type": forms.Select(attrs={"class": _INPUT_CLS}),
            "description": forms.Textarea(
                attrs={
                    "class": _INPUT_CLS,
                    "rows": 3,
                    "placeholder": _("Optional description of policy rationale..."),
                }
            ),
            "min_amount": forms.NumberInput(
                attrs={
                    "class": _MONO_INPUT_CLS,
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "min_discount_percent": forms.NumberInput(
                attrs={
                    "class": _MONO_INPUT_CLS,
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
            "approver_role": forms.Select(attrs={"class": _INPUT_CLS}),
            "approver_user": forms.Select(attrs={"class": _INPUT_CLS}),
            "sort_order": forms.NumberInput(
                attrs={
                    "class": _MONO_INPUT_CLS,
                    "min": "1",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "rounded border-slate-300 text-primary-600 focus:ring-primary-500 h-4 w-4",
                }
            ),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.organization = organization
        # Scope roles and users to this organization
        self.fields["approver_role"].queryset = Role.objects.filter(organization=organization)
        self.fields["approver_role"].empty_label = _("Any Authorized Role (Default)")

        org_user_ids = Membership.all_tenants.filter(organization=organization).values_list(
            "user_id", flat=True
        )
        self.fields["approver_user"].queryset = User.objects.filter(id__in=org_user_ids).order_by("email")
        self.fields["approver_user"].empty_label = _("Any User in Role (Default)")


class ApprovalDecisionForm(forms.Form):
    """Form to submit an approval decision with optional reason notes."""

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": _INPUT_CLS,
                "rows": 3,
                "placeholder": _("Add decision notes or rejection reasons..."),
            }
        ),
        label=_("Decision Notes"),
    )


class ApprovalFilterForm(forms.Form):
    """Form for filtering inbox requests."""

    status = forms.ChoiceField(
        required=False,
        choices=[("", _("All Statuses")), *list(ApprovalStatus.choices)],
        widget=forms.Select(attrs={"class": _FILTER_INPUT_CLS}),
    )
    document_type = forms.ChoiceField(
        required=False,
        choices=[("", _("All Types")), *list(ApprovalRuleType.choices)],
        widget=forms.Select(attrs={"class": _FILTER_INPUT_CLS}),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": _FILTER_INPUT_CLS,
                "placeholder": _("Search reference, title..."),
            }
        ),
    )
