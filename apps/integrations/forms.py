"""Form classes for webhooks configuration and management."""

from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.event_catalog import list_event_catalog
from apps.integrations.models import WebhookEndpoint


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
