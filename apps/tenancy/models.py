"""Organization is the tenant root (global model). Everything else in this app is tenant-scoped."""

from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantModel


class Organization(models.Model):
    public_id = models.UUIDField(default=uuid.uuid7, editable=False, unique=True)
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


class Role(TenantModel):
    """Named bundle of permission codes scoped to an organization."""

    name = models.CharField(_("role name"), max_length=64)
    description = models.CharField(_("description"), max_length=255, blank=True, default="")
    permissions = models.JSONField(_("permission codes"), default=list, blank=True)
    is_system = models.BooleanField(_("system default role"), default=False)

    class Meta:
        verbose_name = _("role")
        verbose_name_plural = _("roles")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_org_role_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def has_permission(self, code: str) -> bool:
        perms = self.permissions or []
        if "*" in perms:
            return True
        if code in perms:
            return True
        # Check wildcard e.g. "sales.*" matches "sales.create"
        prefix = code.split(".", maxsplit=1)[0] + ".*"
        return prefix in perms


class Membership(TenantModel):
    """Links a global User to an Organization with an assigned Role."""

    STATUS_ACTIVE = "active"
    STATUS_INVITED = "invited"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, _("Active")),
        (STATUS_INVITED, _("Invited")),
        (STATUS_SUSPENDED, _("Suspended")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("user"),
    )
    role = models.ForeignKey(
        "tenancy.Role",
        on_delete=models.PROTECT,
        related_name="memberships",
        null=True,
        blank=True,
        verbose_name=_("role"),
    )
    is_owner = models.BooleanField(_("organization owner"), default=False)
    status = models.CharField(_("status"), max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        verbose_name = _("membership")
        verbose_name_plural = _("memberships")
        ordering = ("user__email",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_org_user_membership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} in {self.organization}"


class Branch(TenantModel):
    """Physical branch, office, or store location."""

    name = models.CharField(_("branch name"), max_length=128)
    code = models.CharField(_("code"), max_length=32, blank=True, default="")
    is_headquarters = models.BooleanField(_("headquarters"), default=False)
    is_active = models.BooleanField(default=True)
    address = models.TextField(_("address"), blank=True, default="")
    phone = models.CharField(_("phone"), max_length=32, blank=True, default="")

    class Meta:
        verbose_name = _("branch")
        verbose_name_plural = _("branches")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_org_branch_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MembershipBranch(TenantModel):
    """Restricts a member's scope to specific branches (empty = all branches)."""

    membership = models.ForeignKey(
        "tenancy.Membership",
        on_delete=models.CASCADE,
        related_name="branch_assignments",
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.CASCADE,
        related_name="member_assignments",
    )

    class Meta:
        verbose_name = _("membership branch assignment")
        verbose_name_plural = _("membership branch assignments")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "membership", "branch"],
                name="unique_org_member_branch",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.membership} -> {self.branch}"


class Department(TenantModel):
    """Department within an organization or branch."""

    name = models.CharField(_("department name"), max_length=128)
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departments",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("department")
        verbose_name_plural = _("departments")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_org_department_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Warehouse(TenantModel):
    """Inventory storage location belonging to a branch."""

    name = models.CharField(_("warehouse name"), max_length=128)
    code = models.CharField(_("code"), max_length=32, blank=True, default="")
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.CASCADE,
        related_name="warehouses",
    )
    is_default = models.BooleanField(_("default warehouse"), default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("warehouse")
        verbose_name_plural = _("warehouses")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_org_warehouse_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name


def _default_invitation_token() -> str:
    return secrets.token_urlsafe(32)


class Invitation(TenantModel):
    """Invitation to join an organization with an assigned role."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_EXPIRED = "expired"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_ACCEPTED, _("Accepted")),
        (STATUS_EXPIRED, _("Expired")),
        (STATUS_REVOKED, _("Revoked")),
    ]

    email = models.EmailField(_("invited email"))
    role = models.ForeignKey("tenancy.Role", on_delete=models.PROTECT, related_name="+")
    token = models.CharField(max_length=64, default=_default_invitation_token, editable=False)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    expires_at = models.DateTimeField(_("expires at"))

    class Meta:
        verbose_name = _("invitation")
        verbose_name_plural = _("invitations")
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "token"],
                name="unique_org_invitation_token",
            ),
        ]

    def __str__(self) -> str:
        return f"Invite for {self.email} to {self.organization}"

    @property
    def is_valid(self) -> bool:
        return self.status == self.STATUS_PENDING and timezone.now() < self.expires_at


class OrganizationSettings(TenantModel):
    """Tenant-specific business rules and numbering formats."""

    allow_negative_stock = models.BooleanField(_("allow negative stock"), default=False)
    costing_method = models.CharField(
        _("costing method"),
        max_length=32,
        choices=[("weighted_average", _("Weighted Average")), ("fifo", _("FIFO"))],
        default="weighted_average",
    )
    tax_inclusive_pricing = models.BooleanField(_("tax inclusive pricing"), default=False)
    invoice_prefix = models.CharField(max_length=16, default="INV-")
    quote_prefix = models.CharField(max_length=16, default="QTE-")
    order_prefix = models.CharField(max_length=16, default="ORD-")
    purchase_order_prefix = models.CharField(max_length=16, default="PO-")
    bill_prefix = models.CharField(max_length=16, default="BIL-")
    payment_prefix = models.CharField(max_length=16, default="PAY-")
    receipt_prefix = models.CharField(max_length=16, default="REC-")

    class Meta:
        verbose_name = _("organization settings")
        verbose_name_plural = _("organization settings")
        constraints = [
            models.UniqueConstraint(
                fields=["organization"],
                name="unique_org_settings",
            ),
        ]

    def __str__(self) -> str:
        return f"Settings for {self.organization}"
