"""Forms for AI Assistant chat interactions."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

INPUT_CLASSES = (
    "block w-full rounded-xl border border-line "
    "bg-surface px-4 py-3 text-sm text-ink "
    "placeholder:text-muted focus:border-brand-500 "
    "focus:ring-2 focus:ring-brand-500/20 shadow-xs"
)


class ChatMessageForm(forms.Form):
    """Form for sending a prompt to the AI copilot."""

    content = forms.CharField(
        label=_("Message"),
        widget=forms.TextInput(
            attrs={
                "class": INPUT_CLASSES,
                "placeholder": _("Ask anything... e.g. 'Show sales this month'"),
                "autocomplete": "off",
            }
        ),
    )
    provider = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )
