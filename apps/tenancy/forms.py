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


# ---------------------------------------------------------------------------
# Settings Forms
# ---------------------------------------------------------------------------


class OrganizationProfileForm(forms.Form):
    """Organization legal and geographic profile configuration."""

    name = forms.CharField(
        label=_("Organization Name"), max_length=200, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    base_currency = forms.CharField(
        label=_("Base Currency"), max_length=3, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    country = forms.CharField(
        label=_("Country Code (ISO 2)"),
        max_length=2,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "US"}),
    )
    timezone = forms.CharField(
        label=_("Time Zone"), max_length=64, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    fiscal_year_start = forms.IntegerField(
        label=_("Fiscal Year Start Month (1-12)"),
        min_value=1,
        max_value=12,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    date_format = forms.CharField(
        label=_("Date Format"), max_length=32, widget=forms.TextInput(attrs={"class": "form-input"})
    )


class OrganizationSettingsForm(forms.Form):
    """Tenant business logic and operations switches."""

    allow_negative_stock = forms.BooleanField(
        label=_("Allow Negative Stock"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    costing_method = forms.ChoiceField(
        label=_("Costing Method"),
        choices=[("weighted_average", _("Weighted Average")), ("fifo", _("FIFO"))],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    tax_inclusive_pricing = forms.BooleanField(
        label=_("Tax-Inclusive Pricing"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class BranchForm(forms.Form):
    """Form to create or edit branch records."""

    name = forms.CharField(
        label=_("Branch Name"), max_length=128, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    code = forms.CharField(
        label=_("Branch Code"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    address = forms.CharField(
        label=_("Address"), required=False, widget=forms.Textarea(attrs={"class": "form-textarea", "rows": 2})
    )
    phone = forms.CharField(
        label=_("Phone Number"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    is_headquarters = forms.BooleanField(
        label=_("Headquarters Branch"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class WarehouseForm(forms.Form):
    """Form to create or edit warehouse storage facilities."""

    name = forms.CharField(
        label=_("Warehouse Name"), max_length=128, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    code = forms.CharField(
        label=_("Warehouse Code"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    branch_id = forms.IntegerField(label=_("Branch"), widget=forms.Select(attrs={"class": "form-select"}))
    is_default = forms.BooleanField(
        label=_("Default Warehouse"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class DepartmentForm(forms.Form):
    """Form to create or edit internal departments."""

    name = forms.CharField(
        label=_("Department Name"), max_length=128, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    code = forms.CharField(
        label=_("Department Code"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    parent_id = forms.IntegerField(
        label=_("Parent Department"), required=False, widget=forms.Select(attrs={"class": "form-select"})
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class RoleForm(forms.Form):
    """Form for custom roles and permissions matrix."""

    name = forms.CharField(
        label=_("Role Name"), max_length=64, widget=forms.TextInput(attrs={"class": "form-input"})
    )
    description = forms.CharField(
        label=_("Description"),
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    permissions = forms.MultipleChoiceField(
        label=_("Permissions"),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-checkbox"}),
    )


class InviteMemberForm(forms.Form):
    """Form to invite new user into organization."""

    email = forms.EmailField(
        label=_("Email Address"),
        widget=forms.EmailInput(attrs={"class": "form-input", "placeholder": "user@example.com"}),
    )
    role_id = forms.IntegerField(
        label=_("Assigned Role"), widget=forms.Select(attrs={"class": "form-select"})
    )


class MemberUpdateForm(forms.Form):
    """Form to modify an existing member's role or status."""

    role_id = forms.IntegerField(label=_("Role"), widget=forms.Select(attrs={"class": "form-select"}))
    status = forms.ChoiceField(
        label=_("Status"),
        choices=[("active", _("Active")), ("suspended", _("Suspended"))],
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class NumberSequenceForm(forms.Form):
    """Form to update numbering sequence rules."""

    sequence_prefix = forms.CharField(
        label=_("Prefix"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    suffix = forms.CharField(
        label=_("Suffix"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    next_number = forms.IntegerField(
        label=_("Next Number"), min_value=1, widget=forms.NumberInput(attrs={"class": "form-input"})
    )
    padding = forms.IntegerField(
        label=_("Digit Padding"),
        min_value=1,
        max_value=10,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    reset_frequency = forms.ChoiceField(
        label=_("Reset Frequency"),
        choices=[("never", _("Never")), ("yearly", _("Yearly")), ("monthly", _("Monthly"))],
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class TaxCodeForm(forms.Form):
    """Form to create or update tax codes."""

    code = forms.CharField(
        label=_("Tax Code"),
        max_length=32,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "VAT-20"}),
    )
    name = forms.CharField(
        label=_("Description"),
        max_length=128,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "Standard VAT 20%"}),
    )
    rate = forms.DecimalField(
        label=_("Rate (%)"),
        max_digits=7,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    is_inclusive = forms.BooleanField(
        label=_("Tax Inclusive"), required=False, widget=forms.CheckboxInput(attrs={"class": "form-checkbox"})
    )
    is_default = forms.BooleanField(
        label=_("Default Tax Code"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class CurrencyForm(forms.Form):
    """Form to create or update currency entries."""

    code = forms.CharField(
        label=_("Currency Code (ISO)"),
        max_length=3,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "EUR"}),
    )
    name = forms.CharField(
        label=_("Currency Name"),
        max_length=64,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "Euro"}),
    )
    symbol = forms.CharField(
        label=_("Symbol"),
        max_length=8,
        initial="$",
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "€"}),
    )
    exchange_rate = forms.DecimalField(
        label=_("Exchange Rate to Base"),
        max_digits=18,
        decimal_places=6,
        initial=1.0,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.000001"}),
    )
    is_base = forms.BooleanField(
        label=_("Set as Base Currency"),
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    is_active = forms.BooleanField(
        label=_("Is Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
