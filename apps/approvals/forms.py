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
from apps.tenancy.models import Organization, Role


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
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500",
                    "placeholder": _("e.g. Purchase Order over $5,000"),
                }
            ),
            "rule_type": forms.Select(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500",
                    "rows": 3,
                    "placeholder": _("Optional description of policy rationale..."),
                }
            ),
            "min_amount": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 font-mono",
                    "step": "0.01",
                    "min": "0",
                }
            ),
            "min_discount_percent": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 font-mono",
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                }
            ),
            "approver_role": forms.Select(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500",
                }
            ),
            "approver_user": forms.Select(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500",
                }
            ),
            "sort_order": forms.NumberInput(
                attrs={
                    "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 font-mono",
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

        org_user_ids = organization.memberships.values_list("user_id", flat=True)
        self.fields["approver_user"].queryset = User.objects.filter(id__in=org_user_ids).order_by("email")
        self.fields["approver_user"].empty_label = _("Any User in Role (Default)")


class ApprovalDecisionForm(forms.Form):
    """Form to submit an approval decision with optional reason notes."""

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "w-full rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500",
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
        widget=forms.Select(
            attrs={
                "class": "rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm px-3 py-1.5 focus:ring-2 focus:ring-primary-500",
            }
        ),
    )
    document_type = forms.ChoiceField(
        required=False,
        choices=[("", _("All Types")), *list(ApprovalRuleType.choices)],
        widget=forms.Select(
            attrs={
                "class": "rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm px-3 py-1.5 focus:ring-2 focus:ring-primary-500",
            }
        ),
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "rounded-lg border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white text-sm px-3 py-1.5 focus:ring-2 focus:ring-primary-500",
                "placeholder": _("Search reference, title..."),
            }
        ),
    )
