"""Forms for automation rules creation and editing."""

from __future__ import annotations

import json
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.automation.models import TriggerType

INPUT_CLASSES = (
    "block w-full rounded-lg border border-line "
    "bg-surface px-3.5 py-2 text-sm text-ink "
    "placeholder:text-muted focus:border-brand-500 "
    "focus:ring-1 focus:ring-brand-500 shadow-2xs"
)

CODE_CLASSES = (
    "font-mono block w-full rounded-lg border border-line "
    "bg-surface px-3.5 py-2 text-xs text-ink "
    "placeholder:text-muted focus:border-brand-500 "
    "focus:ring-1 focus:ring-brand-500 shadow-2xs"
)


class AutomationRuleForm(forms.Form):
    """Form for creating or editing an automation rule."""

    name = forms.CharField(
        label=_("Rule Name"),
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES,
                "placeholder": _("e.g. Auto Reorder Low Stock Items"),
            }
        ),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": INPUT_CLASSES,
                "rows": 2,
                "placeholder": _("Optional description of the workflow logic..."),
            }
        ),
    )
    trigger_type = forms.ChoiceField(
        label=_("Trigger Type"),
        choices=TriggerType.choices,
        widget=forms.Select(attrs={"class": INPUT_CLASSES}),
    )
    trigger_event = forms.CharField(
        label=_("Trigger Event"),
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES,
                "placeholder": _("e.g. stock.low, invoice.overdue, customer.inactive"),
            }
        ),
    )
    is_active = forms.BooleanField(
        label=_("Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(
            attrs={
                "class": "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500",
            }
        ),
    )
    conditions_json = forms.CharField(
        label=_("Conditions (JSON)"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": CODE_CLASSES,
                "rows": 4,
                "placeholder": '[{"field": "quantity_on_hand", "operator": "<=", "value": 10}]',
            }
        ),
    )
    actions_json = forms.CharField(
        label=_("Actions (JSON)"),
        widget=forms.Textarea(
            attrs={
                "class": CODE_CLASSES,
                "rows": 4,
                "placeholder": '[{"action_type": "create_draft_po", "params": {"quantity": 25}}]',
            }
        ),
    )

    def clean_conditions_json(self) -> list[dict[str, Any]]:
        raw = self.cleaned_data.get("conditions_json", "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise forms.ValidationError(_("Conditions must be a JSON array of objects."))
            return parsed
        except json.JSONDecodeError as err:
            raise forms.ValidationError(_(f"Invalid JSON in conditions: {err}")) from err

    def clean_actions_json(self) -> list[dict[str, Any]]:
        raw = self.cleaned_data.get("actions_json", "").strip()
        if not raw:
            raise forms.ValidationError(_("Actions are required."))
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list) or len(parsed) == 0:
                raise forms.ValidationError(_("Actions must be a non-empty JSON array."))
            return parsed
        except json.JSONDecodeError as err:
            raise forms.ValidationError(_(f"Invalid JSON in actions: {err}")) from err


class AutomationTestForm(forms.Form):
    """Form to test run an automation rule with mock event data."""

    payload_json = forms.CharField(
        label=_("Mock Event Payload (JSON)"),
        widget=forms.Textarea(
            attrs={
                "class": CODE_CLASSES,
                "rows": 6,
                "placeholder": '{\n  "sku": "PROD-001",\n  "quantity_on_hand": 5\n}',
            }
        ),
    )

    def clean_payload_json(self) -> dict[str, Any]:
        raw = self.cleaned_data.get("payload_json", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise forms.ValidationError(_("Payload must be a JSON object."))
            return parsed
        except json.JSONDecodeError as err:
            raise forms.ValidationError(_(f"Invalid JSON in payload: {err}")) from err
