"""Forms for Reports module: Saved Reports, Schedules, and Report Builder."""

from __future__ import annotations

import datetime
from typing import Any

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.reports.models import (
    ReportSchedule,
    SavedReport,
    ScheduleFrequency,
)

COMMON_INPUT_CLASS = (
    "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white "
    "dark:bg-slate-900 px-3.5 py-2 text-sm text-slate-900 dark:text-white "
    "focus:outline-none focus:ring-2 focus:ring-indigo-500"
)
COMMON_CHECKBOX_CLASS = (
    "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 "
    "dark:border-slate-700 dark:bg-slate-900"
)


class SavedReportForm(forms.ModelForm):
    """Form to create or edit a saved report configuration."""

    class Meta:
        model = SavedReport
        fields = [
            "name",
            "description",
            "is_public",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": COMMON_INPUT_CLASS,
                    "placeholder": _("e.g. High Value Q3 Confirmed Orders"),
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": COMMON_INPUT_CLASS,
                    "rows": 3,
                    "placeholder": _("Brief description of the report's purpose and filters..."),
                }
            ),
            "is_public": forms.CheckboxInput(
                attrs={
                    "class": COMMON_CHECKBOX_CLASS,
                }
            ),
        }


class ReportScheduleForm(forms.ModelForm):
    """Form to configure periodic email delivery of reports."""

    recipient_emails = forms.CharField(
        label=_("Recipient Email Addresses"),
        help_text=_("Comma or line separated email addresses to receive the report."),
        widget=forms.Textarea(
            attrs={
                "class": COMMON_INPUT_CLASS,
                "rows": 2,
                "placeholder": "cfo@company.com, controller@company.com",
            }
        ),
    )

    day_of_week = forms.ChoiceField(
        label=_("Day of Week (for Weekly)"),
        required=False,
        choices=[
            ("", _("Select Day")),
            ("0", _("Monday")),
            ("1", _("Tuesday")),
            ("2", _("Wednesday")),
            ("3", _("Thursday")),
            ("4", _("Friday")),
            ("5", _("Saturday")),
            ("6", _("Sunday")),
        ],
        widget=forms.Select(
            attrs={
                "class": COMMON_INPUT_CLASS,
            }
        ),
    )

    day_of_month = forms.IntegerField(
        label=_("Day of Month (1-31, for Monthly)"),
        required=False,
        min_value=1,
        max_value=31,
        widget=forms.NumberInput(
            attrs={
                "class": COMMON_INPUT_CLASS,
                "placeholder": "1",
            }
        ),
    )

    time_of_day = forms.TimeField(
        label=_("Time of Day (UTC)"),
        required=False,
        initial=datetime.time(8, 0),
        widget=forms.TimeInput(
            attrs={
                "class": COMMON_INPUT_CLASS,
                "type": "time",
            }
        ),
    )

    class Meta:
        model = ReportSchedule
        fields = [
            "name",
            "saved_report",
            "frequency",
            "format",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": COMMON_INPUT_CLASS,
                    "placeholder": _("e.g. Monday Executive Summary"),
                }
            ),
            "saved_report": forms.Select(
                attrs={
                    "class": COMMON_INPUT_CLASS,
                }
            ),
            "frequency": forms.Select(
                attrs={
                    "class": COMMON_INPUT_CLASS,
                }
            ),
            "format": forms.Select(
                attrs={
                    "class": COMMON_INPUT_CLASS,
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": COMMON_CHECKBOX_CLASS,
                }
            ),
        }

    def __init__(self, *args: Any, organization: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.fields["saved_report"].queryset = SavedReport.objects.filter(organization=organization).order_by(
            "name"
        )
        self.fields["saved_report"].empty_label = _("Select a Saved Report")

        if self.instance and self.instance.pk and self.instance.recipients:
            self.fields["recipient_emails"].initial = ", ".join(self.instance.recipients)
            if self.instance.day_of_week is not None:
                self.fields["day_of_week"].initial = str(self.instance.day_of_week)
            if self.instance.day_of_month is not None:
                self.fields["day_of_month"].initial = self.instance.day_of_month
            if self.instance.time_of_day is not None:
                self.fields["time_of_day"].initial = self.instance.time_of_day

    def clean_recipient_emails(self) -> list[str]:
        raw = self.cleaned_data.get("recipient_emails", "")
        # Parse comma or newline separated emails
        parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
        if not parts:
            raise forms.ValidationError(_("At least one email recipient is required."))
        # Basic validation
        validator = forms.EmailField().clean
        valid_emails = []
        for p in parts:
            try:
                valid_emails.append(validator(p))
            except forms.ValidationError as exc:
                raise forms.ValidationError(
                    _("Invalid email address: %(email)s"),
                    params={"email": p},
                ) from exc
        return valid_emails

    def clean(self) -> dict[str, Any]:
        cleaned_data = super().clean()
        freq = cleaned_data.get("frequency")
        dow = cleaned_data.get("day_of_week")
        dom = cleaned_data.get("day_of_month")

        if freq == ScheduleFrequency.WEEKLY and not dow:
            cleaned_data["day_of_week"] = 0  # Default to Monday

        if freq == ScheduleFrequency.MONTHLY and not dom:
            cleaned_data["day_of_month"] = 1  # Default to 1st of month

        if not cleaned_data.get("time_of_day"):
            cleaned_data["time_of_day"] = datetime.time(8, 0)

        return cleaned_data
