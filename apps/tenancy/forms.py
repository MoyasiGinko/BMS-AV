"""Forms for tenancy onboarding and settings."""

from __future__ import annotations

import re

from django import forms
from django.core.validators import validate_email
from django.utils.translation import gettext_lazy as _

from apps.tenancy.models import Organization

CURRENCY_CHOICES = [
    ("USD", "USD - US Dollar ($)"),
    ("EUR", "EUR - Euro (€)"),
    ("GBP", "GBP - British Pound (£)"),
    ("CAD", "CAD - Canadian Dollar (CA$)"),
    ("AUD", "AUD - Australian Dollar (A$)"),
    ("JPY", "JPY - Japanese Yen (¥)"),
    ("CHF", "CHF - Swiss Franc (CHF)"),
    ("SGD", "SGD - Singapore Dollar (S$)"),
]

TIMEZONE_CHOICES = [
    ("UTC", "UTC (Coordinated Universal Time)"),
    ("America/New_York", "America/New York (Eastern Time)"),
    ("America/Chicago", "America/Chicago (Central Time)"),
    ("America/Denver", "America/Denver (Mountain Time)"),
    ("America/Los_Angeles", "America/Los Angeles (Pacific Time)"),
    ("Europe/London", "Europe/London (GMT/BST)"),
    ("Europe/Paris", "Europe/Paris (CET)"),
    ("Europe/Berlin", "Europe/Berlin (CET)"),
    ("Asia/Dubai", "Asia/Dubai (GST)"),
    ("Asia/Singapore", "Asia/Singapore (SGT)"),
    ("Asia/Tokyo", "Asia/Tokyo (JST)"),
    ("Australia/Sydney", "Australia/Sydney (AEST)"),
]

DATE_FORMAT_CHOICES = [
    ("Y-m-d", "YYYY-MM-DD (2026-10-08)"),
    ("m/d/Y", "MM/DD/YYYY (10/08/2026)"),
    ("d/m/Y", "DD/MM/YYYY (08/10/2026)"),
]

PLAN_CHOICES = [
    ("starter", "Starter"),
    ("growth", "Growth"),
    ("business", "Business"),
    ("enterprise", "Enterprise"),
]


class OnboardingStep1Form(forms.Form):
    """Step 1: Organization identity and subscription tier selection."""

    name = forms.CharField(
        label=_("Organization Name"),
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. Apex Global Logistics",
                "class": "form-input",
                "autofocus": "autofocus",
            }
        ),
    )
    slug = forms.SlugField(
        label=_("Workspace Slug"),
        max_length=63,
        widget=forms.TextInput(
            attrs={
                "placeholder": "apex-logistics",
                "class": "form-input",
            }
        ),
    )
    plan = forms.ChoiceField(
        label=_("Plan Tier"),
        choices=PLAN_CHOICES,
        initial="starter",
        widget=forms.RadioSelect,
    )

    def clean_slug(self) -> str:
        slug = self.cleaned_data["slug"].strip().lower()
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", slug):
            raise forms.ValidationError(
                _("Slug must contain only lowercase letters, numbers, and single hyphens.")
            )
        if Organization.objects.filter(slug=slug).exists():
            raise forms.ValidationError(_("This workspace slug is already taken. Please choose another."))
        return slug


class OnboardingStep2Form(forms.Form):
    """Step 2: Regional profile, financial calendar, and facilities."""

    base_currency = forms.ChoiceField(
        label=_("Base Currency"),
        choices=CURRENCY_CHOICES,
        initial="USD",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    country = forms.CharField(
        label=_("Country Code"),
        max_length=2,
        required=False,
        initial="US",
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "US"}),
    )
    timezone = forms.ChoiceField(
        label=_("Time Zone"),
        choices=TIMEZONE_CHOICES,
        initial="UTC",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    fiscal_year_start = forms.IntegerField(
        label=_("Fiscal Year Start Month"),
        min_value=1,
        max_value=12,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    date_format = forms.ChoiceField(
        label=_("Date Format"),
        choices=DATE_FORMAT_CHOICES,
        initial="Y-m-d",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    branch_name = forms.CharField(
        label=_("Headquarters Branch Name"),
        max_length=128,
        initial="Main Branch",
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    warehouse_name = forms.CharField(
        label=_("Default Warehouse Name"),
        max_length=128,
        initial="Main Warehouse",
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )


class OnboardingStep3Form(forms.Form):
    """Step 3: Team member invitations."""

    team_invites = forms.CharField(
        label=_("Invite Team Members"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-textarea",
                "rows": 3,
                "placeholder": "colleague@example.com, manager@example.com",
            }
        ),
        help_text=_("Optional: comma or line-separated email addresses of team members."),
    )

    def clean_team_invites(self) -> list[str]:
        raw = self.cleaned_data.get("team_invites", "")
        if not raw:
            return []

        # Split on commas, semicolons, or newlines
        parts = re.split(r"[\n,;]+", raw)
        clean_emails = []
        for part in parts:
            email = part.strip().lower()
            if not email:
                continue
            try:
                validate_email(email)
                if email not in clean_emails:
                    clean_emails.append(email)
            except forms.ValidationError:
                msg = _("Invalid email address: %(email)s") % {"email": email}
                raise forms.ValidationError(msg) from None
        return clean_emails
