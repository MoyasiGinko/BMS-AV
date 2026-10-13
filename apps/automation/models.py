"""Automation domain models: AutomationRule, AutomationRun, and trigger/action definitions."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantManager, TenantModel


class TriggerType(models.TextChoices):
    EVENT = "event", _("Domain Event")
    SCHEDULE = "schedule", _("Scheduled Scan")


class RunStatus(models.TextChoices):
    SUCCESS = "success", _("Success")
    FAILED = "failed", _("Failed")
    SKIPPED = "skipped", _("Skipped")
    PARTIAL = "partial", _("Partial")


class AutomationRule(TenantModel):
    """Configurable trigger-conditions-actions workflow rule."""

    name = models.CharField(_("rule name"), max_length=255)
    description = models.TextField(_("description"), blank=True, default="")
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    trigger_type = models.CharField(
        _("trigger type"),
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.EVENT,
    )
    trigger_event = models.CharField(
        _("trigger event"),
        max_length=128,
        blank=True,
        default="",
        db_index=True,
        help_text=_("Domain event type, e.g. stock.low, invoice.overdue, customer.inactive"),
    )
    trigger_config = models.JSONField(
        _("trigger configuration"),
        default=dict,
        blank=True,
        help_text=_("Parameters for schedule-based triggers or event filters"),
    )
    conditions = models.JSONField(
        _("conditions"),
        default=list,
        blank=True,
        help_text=_(
            "List of declarative condition dicts: [{'field': '...', 'operator': '...', 'value': ...}]"
        ),
    )
    actions = models.JSONField(
        _("actions"),
        default=list,
        help_text=_("List of action dicts: [{'action_type': '...', 'params': {...}}]"),
    )
    template_key = models.CharField(
        _("template key"),
        max_length=64,
        blank=True,
        default="",
        help_text=_("Source template key if instantiated from library"),
    )
    execution_count = models.PositiveIntegerField(_("execution count"), default=0)
    last_run_at = models.DateTimeField(_("last run at"), null=True, blank=True)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("automation rule")
        verbose_name_plural = _("automation rules")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_org_automation_rule_name",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active", "trigger_type", "trigger_event"]),
            models.Index(fields=["organization", "last_run_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_trigger_type_display()})"


class AutomationRun(TenantModel):
    """Immutable execution log of an automation rule."""

    rule = models.ForeignKey(
        AutomationRule,
        on_delete=models.CASCADE,
        related_name="runs",
        verbose_name=_("automation rule"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=RunStatus.choices,
        default=RunStatus.SUCCESS,
        db_index=True,
    )
    trigger_event_type = models.CharField(_("trigger event type"), max_length=128)
    trigger_payload = models.JSONField(_("trigger payload"), default=dict, blank=True)
    actions_executed = models.JSONField(_("actions executed"), default=list, blank=True)
    error_message = models.TextField(_("error message"), blank=True, default="")
    execution_time_ms = models.PositiveIntegerField(_("execution time (ms)"), default=0)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("automation run")
        verbose_name_plural = _("automation runs")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "rule", "-created_at"]),
            models.Index(fields=["organization", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Run {self.public_id} - {self.rule.name} ({self.status})"
