"""Organization is the tenant root (global model). Everything else in this app is tenant-scoped."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class Organization(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    name = models.CharField(_("name"), max_length=200)
    slug = models.SlugField(_("slug"), max_length=63, unique=True)
    base_currency = models.CharField(_("base currency"), max_length=3, default="USD")
    country = models.CharField(_("country"), max_length=2, blank=True)
    timezone = models.CharField(_("time zone"), max_length=64, default="UTC")
    fiscal_year_start = models.PositiveSmallIntegerField(_("fiscal year start month"), default=1)
    date_format = models.CharField(_("date format"), max_length=20, default="Y-m-d")
    settings = models.JSONField(_("settings"), default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = _("organization")
        verbose_name_plural = _("organizations")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(fiscal_year_start__gte=1) & models.Q(fiscal_year_start__lte=12),
                name="org_fiscal_year_start_month_range",
            ),
        ]

    def __str__(self) -> str:
        return self.name
