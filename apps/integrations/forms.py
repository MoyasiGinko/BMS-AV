from __future__ import annotations

import json
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.event_catalog import list_event_catalog
from apps.integrations.models import IntegrationConnection, WebhookEndpoint


class WebhookEndpointForm(forms.ModelForm):
    """Form to create or update a tenant webhook destination endpoint."""

    INPUT_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 "
        "placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    )

    url = forms.URLField(
        label=_("Payload URL"),
        help_text=_("The destination HTTPS URL where signed POST payloads will be sent."),
        widget=forms.URLInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": "https://api.yourcompany.com/webhooks/businessos",
            }
        ),
    )
    description = forms.CharField(
        label=_("Description"),
        required=False,
        help_text=_("Optional friendly label (e.g. 'Production Zapier connector' or 'Accounting Sync')."),
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CSS,
                "placeholder": "ERP sync endpoint",
            }
        ),
    )
    selected_events = forms.MultipleChoiceField(
        label=_("Subscribed Events"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Select which domain events this endpoint should receive, or leave empty for all."),
    )
    is_active = forms.BooleanField(
        label=_("Active"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(
            attrs={
                "class": (
                    "h-4 w-4 rounded border-slate-300 text-indigo-600 "
                    "focus:ring-indigo-500 dark:border-slate-700 dark:bg-slate-900"
                ),
            }
        ),
    )

    class Meta:
        model = WebhookEndpoint
        fields = ["url", "description", "is_active"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        choices: list[tuple[str, str]] = [("*", str(_("All Events (*)")))]
        for defn in list_event_catalog():
            choices.append((defn.event_type, f"{defn.event_type} - {defn.description}"))
        self.fields["selected_events"].choices = choices

        if self.instance and self.instance.pk:
            current_events = self.instance.events or ["*"]
            self.fields["selected_events"].initial = current_events
        else:
            self.fields["selected_events"].initial = ["*"]

    def clean_selected_events(self) -> list[str]:
        chosen = self.cleaned_data.get("selected_events") or []
        if not chosen or "*" in chosen:
            return ["*"]
        return chosen


class IntegrationConnectionForm(forms.ModelForm):
    """Form to create or update an external IntegrationConnection instance."""

    INPUT_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 "
        "placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    )
    MONO_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "dark:bg-slate-900 px-3 py-2 font-mono text-xs text-slate-900 dark:text-slate-100 "
        "placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    )

    config_json = forms.CharField(
        label=_("Configuration (JSON)"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": MONO_CSS,
                "rows": 5,
                "placeholder": '{\n  "base_url": "https://api.partner.com/v1"\n}',
            }
        ),
        help_text=_("JSON object of connection parameters (endpoint paths, options, field mappings)."),
    )

    credentials_json = forms.CharField(
        label=_("Credentials (JSON - Encrypted at rest)"),
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": MONO_CSS,
                "rows": 3,
                "placeholder": '{\n  "api_key": "sec_...",\n  "token": "..."\n}',
            }
        ),
        help_text=_("Sensitive secrets, API keys, and passwords encrypted with symmetric Fernet at rest."),
    )

    class Meta:
        model = IntegrationConnection
        fields = [
            "name",
            "connector_type",
            "status",
            "description",
            "sync_interval_minutes",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": _("e.g. Production Shopify Store / Partner REST API"),
                }
            ),
            "connector_type": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "rows": 2,
                    "placeholder": _("Brief description of what this integration synchronizes..."),
                }
            ),
            "sync_interval_minutes": forms.NumberInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-white dark:bg-slate-900 px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.config:
                self.fields["config_json"].initial = json.dumps(self.instance.config, indent=2)
            if self.instance.credentials:
                sensitive_tokens = ("key", "secret", "pass", "token")
                masked_creds = {
                    k: ("*" * 8 if any(token in k.lower() for token in sensitive_tokens) else v)
                    for k, v in self.instance.credentials.items()
                }
                self.fields["credentials_json"].initial = json.dumps(masked_creds, indent=2)

    def clean_config_json(self) -> dict[str, Any]:
        raw = self.cleaned_data.get("config_json", "")
        if isinstance(raw, dict):
            return raw
        if not raw or not str(raw).strip():
            return {}

        try:
            val = json.loads(str(raw).strip())
            if not isinstance(val, dict):
                raise forms.ValidationError(_("Configuration must be a JSON object ({...})."))
            return val
        except json.JSONDecodeError as exc:
            msg = _("Invalid JSON in configuration: %(err)s")
            raise forms.ValidationError(msg, params={"err": str(exc)}) from exc

    def clean_credentials_json(self) -> dict[str, Any] | None:
        raw = self.cleaned_data.get("credentials_json", "")
        if isinstance(raw, dict):
            return raw
        if not raw or not str(raw).strip():
            return None

        try:
            val = json.loads(str(raw).strip())
            if not isinstance(val, dict):
                raise forms.ValidationError(_("Credentials must be a JSON object ({...})."))
            # If values were left as "********", keep existing credentials from instance
            if self.instance and self.instance.pk:
                existing = self.instance.credentials or {}
                for k, v in val.items():
                    if v == "********" and k in existing:
                        val[k] = existing[k]
            return val
        except json.JSONDecodeError as exc:
            msg = _("Invalid JSON in credentials: %(err)s")
            raise forms.ValidationError(msg, params={"err": str(exc)}) from exc
