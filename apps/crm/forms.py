"""Django Forms for CRM leads, opportunities, interactions, and tasks."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.crm.models import (
    CrmTask,
    Interaction,
    Lead,
    Opportunity,
    Pipeline,
    Stage,
)
from apps.customers.models import Customer
from apps.tenancy.models import Organization

User = get_user_model()


class LeadForm(forms.ModelForm):
    tags_csv = forms.CharField(
        label=_("Tags (comma separated)"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "VIP, Inbound, Q3-Target"}),
    )

    class Meta:
        model = Lead
        fields = [
            "first_name",
            "last_name",
            "company_name",
            "email",
            "phone",
            "title",
            "source",
            "status",
            "estimated_value",
            "assigned_to",
            "notes",
        ]

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(
            memberships__organization=organization
        ).distinct()
        if self.instance and self.instance.pk:
            self.fields["tags_csv"].initial = ", ".join(t.name for t in self.instance.tags.all())


class OpportunityForm(forms.ModelForm):
    tags_csv = forms.CharField(
        label=_("Tags (comma separated)"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Enterprise, Fast-track"}),
    )

    class Meta:
        model = Opportunity
        fields = [
            "title",
            "pipeline",
            "stage",
            "customer",
            "expected_value",
            "probability_percent",
            "expected_close_date",
            "assigned_to",
            "notes",
        ]
        widgets = {
            "expected_close_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["pipeline"].queryset = Pipeline.all_tenants.filter(
            organization=organization, is_active=True
        )
        self.fields["stage"].queryset = Stage.all_tenants.filter(organization=organization)
        self.fields["customer"].queryset = Customer.all_tenants.filter(
            organization=organization, status="active"
        )
        self.fields["assigned_to"].queryset = User.objects.filter(
            memberships__organization=organization
        ).distinct()
        if self.instance and self.instance.pk:
            self.fields["tags_csv"].initial = ", ".join(t.name for t in self.instance.tags.all())


class InteractionForm(forms.ModelForm):
    class Meta:
        model = Interaction
        fields = [
            "type",
            "summary",
            "details",
        ]
        widgets = {
            "details": forms.Textarea(attrs={"rows": 3}),
        }


class CrmTaskForm(forms.ModelForm):
    class Meta:
        model = CrmTask
        fields = [
            "title",
            "description",
            "due_date",
            "priority",
            "assigned_to",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args: Any, organization: Organization, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(
            memberships__organization=organization
        ).distinct()
