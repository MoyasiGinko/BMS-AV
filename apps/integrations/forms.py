from __future__ import annotations

import json
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.event_catalog import list_event_catalog
from apps.integrations.models import (
    DataRetentionPolicy,
    DataSubjectRequest,
    InboundWebhookEndpoint,
    IntegrationConnection,
    OAuthApplication,
    WebhookEndpoint,
)


class WebhookEndpointForm(forms.ModelForm):
    """Form to create or update a tenant webhook destination endpoint."""

    INPUT_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "bg-surface px-3 py-2 text-sm text-slate-900 dark:text-slate-100 "
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
                    "focus:ring-brand-500 border-line bg-surface"
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
        selected_field = self.fields.get("selected_events")
        if isinstance(selected_field, forms.ChoiceField):
            selected_field.choices = choices

        if self.instance and self.instance.pk:
            current_events = self.instance.events or ["*"]
            if selected_field:
                selected_field.initial = current_events
        elif selected_field:
            selected_field.initial = ["*"]

    def clean_selected_events(self) -> list[str]:
        chosen = self.cleaned_data.get("selected_events") or []
        if not chosen or "*" in chosen:
            return ["*"]
        return chosen


class IntegrationConnectionForm(forms.ModelForm):
    """Form to create or update an external IntegrationConnection instance."""

    INPUT_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "bg-surface px-3 py-2 text-sm text-slate-900 dark:text-slate-100 "
        "placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    )
    MONO_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "bg-surface px-3 py-2 font-mono text-xs text-slate-900 dark:text-slate-100 "
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
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
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
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
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
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
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


class OAuthApplicationForm(forms.ModelForm):
    """Form to create or update an OAuth2 application for a tenant."""

    INPUT_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "bg-surface px-3 py-2 text-sm text-slate-900 dark:text-slate-100 "
        "placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    )

    SCOPE_CHOICES = [
        ("read", _("Read basic resources")),
        ("write", _("Write basic resources")),
        ("admin", _("Full tenant administrator access")),
        ("catalog:read", _("View catalog products")),
        ("catalog:write", _("Manage catalog products")),
        ("inventory:read", _("View inventory stock")),
        ("inventory:write", _("Manage stock movements")),
        ("sales:read", _("View sales orders")),
        ("sales:write", _("Create/manage sales orders")),
        ("purchasing:read", _("View purchase orders")),
        ("purchasing:write", _("Manage purchase orders")),
        ("customers:read", _("View customers")),
        ("customers:write", _("Manage customers")),
        ("accounting:read", _("View journal entries and accounts")),
        ("accounting:write", _("Post journal entries")),
        ("reports:read", _("Run and export reports")),
        ("integrations:read", _("View integrations")),
        ("integrations:write", _("Manage integrations and webhooks")),
    ]

    scopes = forms.MultipleChoiceField(
        label=_("Allowed Scopes"),
        choices=SCOPE_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
        ),
        help_text=_("Select API scopes this application is permitted to request."),
    )

    class Meta:
        model = OAuthApplication
        fields = [
            "name",
            "client_type",
            "authorization_grant_type",
            "redirect_uris",
            "description",
            "skip_authorization",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": _("e.g. Zapier Integration / Warehouse Scanner SPA"),
                }
            ),
            "client_type": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "authorization_grant_type": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "redirect_uris": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 font-mono text-xs text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "rows": 2,
                    "placeholder": "https://myapp.com/oauth/callback\nhttps://oauth.pstmn.io/v1/callback",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "rows": 2,
                    "placeholder": _("Purpose and system usage of this OAuth application..."),
                }
            ),
            "skip_authorization": forms.CheckboxInput(
                attrs={"class": "rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"}
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            current_scopes = (self.instance.allowed_scopes or "").split()
            self.fields["scopes"].initial = current_scopes
        else:
            self.fields["scopes"].initial = ["read"]

    def clean_scopes(self) -> str:
        chosen = self.cleaned_data.get("scopes", [])
        return " ".join(chosen) if chosen else "read"


class InboundWebhookEndpointForm(forms.ModelForm):
    """Form to create or update an inbound webhook endpoint for receiving external notifications."""

    INPUT_CSS = (
        "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
        "bg-surface px-3 py-2 text-sm text-slate-900 dark:text-slate-100 "
        "placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    )

    custom_secret = forms.CharField(
        label=_("Signing Secret"),
        required=False,
        widget=forms.PasswordInput(
            render_value=True,
            attrs={
                "class": (
                    "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                    "bg-surface px-3 py-2 font-mono text-xs text-slate-900 "
                    "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                    "focus:ring-1 focus:ring-indigo-500"
                ),
                "placeholder": _("Leave blank to auto-generate a secure random 32-byte secret"),
            },
        ),
        help_text=_(
            "Shared secret used to verify incoming webhook signatures. Auto-generated if left empty."
        ),
    )

    class Meta:
        model = InboundWebhookEndpoint
        fields = [
            "name",
            "provider",
            "signature_header",
            "signature_algorithm",
            "target_event",
            "status",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": _("e.g. Stripe Payment Events / Shopify Order Notifications"),
                }
            ),
            "provider": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "signature_header": forms.TextInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 font-mono text-xs text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": "X-Signature, Stripe-Signature, X-Hub-Signature-256",
                }
            ),
            "signature_algorithm": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "target_event": forms.TextInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 font-mono text-xs text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": "inbound_webhook.received",
                }
            ),
            "status": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 placeholder-slate-400 focus:outline-none "
                        "focus:ring-1 focus:ring-indigo-500"
                    ),
                    "rows": 2,
                    "placeholder": _("Brief description of the external service sending webhooks..."),
                }
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.secret:
            self.fields["custom_secret"].initial = self.instance.secret


class TenantExportJobForm(forms.Form):
    """Form to request a full-tenant data export archive."""

    include_audit_logs = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Include Audit Logs"),
        help_text=_("Include administrative audit logs (up to 5,000 recent events) in the export archive."),
        widget=forms.CheckboxInput(
            attrs={
                "class": (
                    "h-4 w-4 rounded border-slate-300 text-indigo-600 "
                    "focus:ring-brand-500 border-line bg-surface"
                ),
            }
        ),
    )


class TenantImportJobForm(forms.Form):
    """Form to upload a full-tenant data backup archive."""

    file = forms.FileField(
        required=True,
        label=_("Backup Archive (.zip)"),
        help_text=_("Upload a valid BMS-AV ERP tenant backup ZIP file containing manifest.json."),
        widget=forms.FileInput(
            attrs={
                "class": (
                    "block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 "
                    "file:rounded-md file:border-0 file:text-sm file:font-semibold "
                    "file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 "
                    "dark:file:bg-indigo-900/40 dark:file:text-indigo-300"
                ),
                "accept": ".zip,application/zip",
            }
        ),
    )

    def clean_file(self) -> Any:
        file = self.cleaned_data.get("file")
        if file:
            if not file.name.lower().endswith(".zip"):
                raise forms.ValidationError(_("The uploaded file must be a .zip archive."))
            # Max 50MB check
            if file.size > 50 * 1024 * 1024:
                raise forms.ValidationError(_("The backup file cannot exceed 50 MB."))
        return file


class DataRetentionPolicyForm(forms.ModelForm):
    """Form to configure tenant data lifecycle and log retention policies."""

    class Meta:
        model = DataRetentionPolicy
        fields = [
            "audit_log_retention_days",
            "webhook_log_retention_days",
            "sync_log_retention_days",
            "export_file_retention_days",
            "is_active",
        ]
        widgets = {
            "audit_log_retention_days": forms.NumberInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "min": 30,
                }
            ),
            "webhook_log_retention_days": forms.NumberInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "min": 7,
                }
            ),
            "sync_log_retention_days": forms.NumberInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "min": 7,
                }
            ),
            "export_file_retention_days": forms.NumberInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "min": 1,
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": (
                        "h-4 w-4 rounded border-slate-300 text-indigo-600 "
                        "focus:ring-brand-500 border-line bg-surface"
                    ),
                }
            ),
        }


class DataSubjectRequestForm(forms.ModelForm):
    """Form to submit a GDPR Right to Access or Right to Erasure request."""

    class Meta:
        model = DataSubjectRequest
        fields = [
            "subject_email",
            "request_type",
            "subject_name",
            "subject_type",
            "reason",
            "verification_notes",
        ]
        widgets = {
            "subject_email": forms.EmailInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": "user@example.com",
                }
            ),
            "request_type": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "subject_name": forms.TextInput(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "placeholder": "Full name of the data subject",
                }
            ),
            "subject_type": forms.Select(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                }
            ),
            "reason": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "rows": 2,
                    "placeholder": _("Reason or details of the privacy request..."),
                }
            ),
            "verification_notes": forms.Textarea(
                attrs={
                    "class": (
                        "w-full rounded-lg border border-slate-300 dark:border-slate-700 "
                        "bg-surface px-3 py-2 text-sm text-slate-900 "
                        "dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    ),
                    "rows": 2,
                    "placeholder": _("Identity verification details and proof verified..."),
                }
            ),
        }
