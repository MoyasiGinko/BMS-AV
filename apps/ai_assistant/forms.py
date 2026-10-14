"""Forms for AI Assistant chat interactions."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

INPUT_CLASSES = (
    "block w-full rounded-xl border border-slate-300 dark:border-slate-700 "
    "bg-white dark:bg-slate-900 px-4 py-3 text-sm text-slate-900 "
    "dark:text-slate-100 placeholder-slate-400 focus:border-indigo-500 "
    "focus:ring-2 focus:ring-indigo-500/20 shadow-sm"
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
