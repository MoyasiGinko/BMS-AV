"""Billing domain models: Plan, Module, PlanModule, Subscription, and UsageCounter."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, ClassVar

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantManager, TenantModel


class Plan(models.Model):
    """Platform subscription tier defined by SaaS operator (e.g. Starter, Growth, Business, Enterprise)."""

    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
    name = models.CharField(_("plan name"), max_length=64)
    slug = models.SlugField(_("slug"), max_length=64, unique=True)
    description = models.TextField(_("description"), blank=True, default="")
    price_monthly = models.DecimalField(
        _("monthly price"), max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    price_yearly = models.DecimalField(
        _("yearly price"), max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    currency = models.CharField(_("currency"), max_length=3, default="USD")
    is_active = models.BooleanField(_("active"), default=True)
    trial_days = models.PositiveIntegerField(_("trial period in days"), default=14)

    # Entitlement resource quotas (-1 denotes unlimited)
    max_users = models.IntegerField(_("maximum users"), default=-1)
    max_branches = models.IntegerField(_("maximum branches"), default=-1)
    max_warehouses = models.IntegerField(_("maximum warehouses"), default=-1)

    sort_order = models.PositiveIntegerField(_("sort order"), default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("plan")
        verbose_name_plural = _("plans")
        ordering = ("sort_order", "price_monthly")

    def __str__(self) -> str:
        return f"{self.name} (${self.price_monthly}/mo)"


class Module(models.Model):
    """System functional module (e.g., catalog, inventory, sales, accounting, pos, etc.)."""

    key = models.SlugField(_("module key"), max_length=64, unique=True)
    name = models.CharField(_("module name"), max_length=64)
    description = models.TextField(_("description"), blank=True, default="")
    icon = models.CharField(_("icon identifier"), max_length=64, default="cube")
    is_beta = models.BooleanField(_("beta feature"), default=False)
    sort_order = models.PositiveIntegerField(_("sort order"), default=0)

    class Meta:
        verbose_name = _("module")
        verbose_name_plural = _("modules")
        ordering = ("sort_order", "name")

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class PlanModule(models.Model):
    """Associates a module with a plan tier."""

    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name="plan_modules")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="module_plans")
    included = models.BooleanField(_("included in plan"), default=True)

    class Meta:
        verbose_name = _("plan module")
        verbose_name_plural = _("plan modules")
        constraints = [
            models.UniqueConstraint(fields=["plan", "module"], name="uniq_plan_module"),
        ]

    def __str__(self) -> str:
        status_text = "included" if self.included else "excluded"
        return f"{self.plan.name} -> {self.module.name} ({status_text})"


class Subscription(TenantModel):
    """Tenant organization's current subscription lifecycle."""

    STATUS_TRIALING = "trialing"
    STATUS_ACTIVE = "active"
    STATUS_PAST_DUE = "past_due"
    STATUS_CANCELED = "canceled"
    STATUS_PAUSED = "paused"

    STATUS_CHOICES = [
        (STATUS_TRIALING, _("Trialing")),
        (STATUS_ACTIVE, _("Active")),
        (STATUS_PAST_DUE, _("Past Due")),
        (STATUS_CANCELED, _("Canceled")),
        (STATUS_PAUSED, _("Paused")),
    ]

    INTERVAL_MONTHLY = "monthly"
    INTERVAL_YEARLY = "yearly"

    INTERVAL_CHOICES = [
        (INTERVAL_MONTHLY, _("Monthly")),
        (INTERVAL_YEARLY, _("Yearly")),
    ]

    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name=_("plan"),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_TRIALING,
        db_index=True,
    )
    billing_interval = models.CharField(
        _("billing interval"),
        max_length=10,
        choices=INTERVAL_CHOICES,
        default=INTERVAL_MONTHLY,
    )

    trial_start = models.DateTimeField(_("trial start"), null=True, blank=True)
    trial_end = models.DateTimeField(_("trial end"), null=True, blank=True)
    current_period_start = models.DateTimeField(_("period start"), null=True, blank=True)
    current_period_end = models.DateTimeField(_("period end"), null=True, blank=True)
    renews_at = models.DateTimeField(_("renews at"), null=True, blank=True)

    cancel_at_period_end = models.BooleanField(_("cancel at period end"), default=False)
    canceled_at = models.DateTimeField(_("canceled at"), null=True, blank=True)
    payment_method_id = models.CharField(_("payment method ID"), max_length=128, blank=True, default="")

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("subscription")
        verbose_name_plural = _("subscriptions")
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="uniq_org_subscription"),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.organization} - {self.plan.name} ({self.status})"

    @property
    def is_active_or_trialing(self) -> bool:
        """Returns True if the tenant is in good standing and can access plan features."""
        if self.status == self.STATUS_ACTIVE:
            return True
        return self.status == self.STATUS_TRIALING and (
            self.trial_end is None or self.trial_end >= timezone.now()
        )


class UsageCounter(TenantModel):
    """Tracks resource consumption against plan limits for a period."""

    metric = models.CharField(_("metric name"), max_length=64, db_index=True)
    value = models.BigIntegerField(_("current count"), default=0)
    period_start = models.DateField(_("period start date"))
    period_end = models.DateField(_("period end date"))

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("usage counter")
        verbose_name_plural = _("usage counters")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "metric", "period_start"],
                name="uniq_org_metric_period",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "metric", "period_start"]),
        ]

    def __str__(self) -> str:
        return f"[{self.organization}] {self.metric}: {self.value}"
