"""Tenant-scoped base model and manager.
Every business model inherits TenantModel (see tests/architecture).
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, TypeVar

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.tenant_context import get_current_organization_id

_M = TypeVar("_M", bound=models.Model)


class TenantQuerySet(models.QuerySet[_M]):
    def for_organization(self, organization_id: int) -> TenantQuerySet[_M]:
        return self.filter(organization_id=organization_id)


class TenantManager(models.Manager[_M]):
    """Default manager: auto-filters by the active tenant; returns nothing when no tenant is active."""

    def get_queryset(self) -> TenantQuerySet[_M]:
        qs: TenantQuerySet[_M] = TenantQuerySet(self.model, using=self._db)
        org_id = get_current_organization_id()
        if org_id is None:
            return qs.none()
        return qs.filter(organization_id=org_id)


class TenantModel(models.Model):
    """Abstract base for tenant-owned rows: organization FK, public UUID, audit timestamps, creator."""

    organization = models.ForeignKey(
        "tenancy.Organization",
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("organization"),
        editable=False,
    )
    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        editable=False,
    )

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    # Unscoped manager: system code only (migrations, dispatchers, back-office).
    # Always comment why it is used.
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self._meta.verbose_name} {self.public_id}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if getattr(self, "organization_id", None) is None:
            org_id = get_current_organization_id()
            if org_id is not None:
                self.organization_id = org_id
        super().save(*args, **kwargs)
