"""Tenant-scoped base model and manager.
Every business model inherits TenantModel (see tests/architecture).
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar, TypeVar

from django.conf import settings
from django.db import models
from django.utils import timezone
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
    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
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


class NumberSequence(TenantModel):
    """Generates sequential document numbers per organization (e.g. INV-2026-00001)."""

    RESET_NEVER = "never"
    RESET_YEARLY = "yearly"
    RESET_MONTHLY = "monthly"
    RESET_CHOICES = [
        (RESET_NEVER, _("Never")),
        (RESET_YEARLY, _("Yearly")),
        (RESET_MONTHLY, _("Monthly")),
    ]

    name = models.CharField(_("sequence name"), max_length=64)
    prefix = models.CharField(_("prefix"), max_length=32, blank=True, default="")
    suffix = models.CharField(_("suffix"), max_length=32, blank=True, default="")
    next_number = models.PositiveIntegerField(_("next number"), default=1)
    padding = models.PositiveSmallIntegerField(_("padding digits"), default=5)
    reset_frequency = models.CharField(
        _("reset frequency"),
        max_length=16,
        choices=RESET_CHOICES,
        default=RESET_NEVER,
    )
    last_reset_date = models.DateField(_("last reset date"), null=True, blank=True)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("number sequence")
        verbose_name_plural = _("number sequences")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_org_number_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}...)"


class AuditLog(TenantModel):
    """Immutable audit log recording sensitive actions and state changes within a tenant."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name=_("actor"),
    )
    action = models.CharField(_("action"), max_length=128, db_index=True)
    target_type = models.CharField(
        _("target model type"), max_length=128, blank=True, default="", db_index=True
    )
    target_id = models.CharField(_("target object ID"), max_length=64, blank=True, default="", db_index=True)
    object_repr = models.CharField(_("object representation"), max_length=255, blank=True, default="")
    changes = models.JSONField(_("changes diff"), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.TextField(_("user agent"), blank=True, default="")

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("audit log")
        verbose_name_plural = _("audit logs")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["organization", "action", "-created_at"]),
            models.Index(fields=["organization", "target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return f"[{self.created_at}] {self.action} on {self.object_repr or self.target_type}"


class ApiKey(TenantModel):
    """Scoped, hashed API key for authenticating external integrations and APIs."""

    name = models.CharField(_("key name"), max_length=128)
    prefix = models.CharField(_("key prefix"), max_length=24, db_index=True)
    key_hash = models.CharField(_("hashed secret"), max_length=128, db_index=True)
    scopes = models.JSONField(_("granted scopes"), default=list, blank=True)
    ip_allowlist = models.JSONField(_("IP allowlist"), default=list, blank=True)
    expires_at = models.DateTimeField(_("expiration time"), null=True, blank=True)
    last_used_at = models.DateTimeField(_("last used time"), null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(_("last used IP"), null=True, blank=True)
    is_active = models.BooleanField(_("is active"), default=True)
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revoked_api_keys",
        verbose_name=_("revoked by"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_keys",
        verbose_name=_("associated user"),
        help_text=_("User identity used for role and audit correlation."),
    )
    rotated_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotations",
        verbose_name=_("rotated from"),
    )

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("API key")
        verbose_name_plural = _("API keys")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "prefix"],
                name="unique_org_apikey_prefix",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "prefix"]),
            models.Index(fields=["prefix", "key_hash"]),
            models.Index(fields=["organization", "is_active", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}...)"

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.is_active and self.revoked_at is None and not self.is_expired


class OutboxEvent(models.Model):
    """Transactional Outbox event. Published in caller's transaction; dispatched asynchronously."""

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_PROCESSED = "processed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_PROCESSING, _("Processing")),
        (STATUS_PROCESSED, _("Processed")),
        (STATUS_FAILED, _("Failed")),
    ]

    id = models.BigAutoField(primary_key=True)
    event_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    organization = models.ForeignKey(
        "tenancy.Organization",
        on_delete=models.CASCADE,
        related_name="outbox_events",
        verbose_name=_("organization"),
        null=True,
        blank=True,
        db_index=True,
    )
    event_type = models.CharField(_("event type"), max_length=128, db_index=True)
    payload = models.JSONField(_("payload"), default=dict)
    headers = models.JSONField(_("headers"), default=dict, blank=True)
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    retry_count = models.PositiveIntegerField(_("retry count"), default=0)
    last_error = models.TextField(_("last error"), blank=True, default="")
    created_at = models.DateTimeField(_("created at"), auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(_("processed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("outbox event")
        verbose_name_plural = _("outbox events")
        ordering = ("created_at",)
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["organization", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} ({self.event_id}) [{self.status}]"
