"""Organization is the tenant root (global model). Everything else in this app is tenant-scoped."""

from __future__ import annotations

import secrets
import uuid
from decimal import Decimal
from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantManager, TenantModel


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

    @property
    def status(self) -> str:
        return self.settings.get("status", "active" if self.is_active else "suspended")

    @property
    def currency(self) -> str:
        return self.base_currency


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

    @property
    def is_superadmin(self) -> bool:
        """Check if this role is the hardcoded Superadmin authority role."""
        return self.name.strip().lower() in ("superadmin", "super admin", "owner")

    def has_permission(self, code: str) -> bool:
        if self.is_superadmin:
            return True
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
    warehouses = models.ManyToManyField(
        "tenancy.Warehouse",
        through="tenancy.BranchWarehouse",
        related_name="linked_branches",
        blank=True,
    )

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
    code = models.CharField(_("code"), max_length=32, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
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


class WarehouseType(models.TextChoices):
    PRIMARY = "primary", _("Primary Warehouse")
    SECONDARY = "secondary", _("Secondary Warehouse")


class Warehouse(TenantModel):
    """Inventory storage location: primary hub or secondary feeder, with or without linked branches."""

    name = models.CharField(_("warehouse name"), max_length=128)
    code = models.CharField(_("code"), max_length=32, blank=True, default="")
    warehouse_type = models.CharField(
        _("warehouse type"),
        max_length=32,
        choices=WarehouseType.choices,
        default=WarehouseType.PRIMARY,
        help_text=_("Primary hub or secondary feeder warehouse."),
    )
    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="co_located_warehouses",
        help_text=_("Physical branch where this warehouse is on premise, or null if standalone."),
    )
    is_central = models.BooleanField(
        _("central distribution warehouse"),
        default=False,
        help_text=_("Designates a central distribution hub that supplies multiple branches."),
    )
    is_default = models.BooleanField(_("organization default warehouse"), default=False)
    is_active = models.BooleanField(default=True)

    @property
    def is_primary(self) -> bool:
        return self.warehouse_type == WarehouseType.PRIMARY

    @property
    def is_secondary(self) -> bool:
        return self.warehouse_type == WarehouseType.SECONDARY

    def get_sellable_location(self) -> Any:
        """Dedicated location for products sold through outlets."""
        custom_loc = (
            self.inventory_locations.filter(
                custom_storage_type__can_sell=True,
                custom_storage_type__is_active=True,
                is_active=True,
            )
            .order_by("-custom_storage_type__is_default_sellable", "name")
            .first()
        )
        if custom_loc:
            return custom_loc

        return (
            self.inventory_locations.filter(storage_type="sellable", is_active=True).first()
            or self.inventory_locations.filter(is_active=True).first()
            or self.inventory_locations.first()
        )

    def get_sellable_locations(self) -> list[Any]:
        """All locations from which products can be sold through outlets."""
        custom_locs = list(
            self.inventory_locations.filter(
                custom_storage_type__can_sell=True,
                custom_storage_type__is_active=True,
                is_active=True,
            ).order_by("-custom_storage_type__is_default_sellable", "name")
        )
        if custom_locs:
            return custom_locs

        return list(
            self.inventory_locations.filter(storage_type="sellable", is_active=True)
        )

    def get_internal_location(self) -> Any:
        """Dedicated location for raw materials, ingredients, and non-sale goods."""
        custom_loc = (
            self.inventory_locations.filter(
                custom_storage_type__can_sell=False,
                custom_storage_type__is_active=True,
                is_active=True,
            ).first()
        )
        if custom_loc:
            return custom_loc

        return (
            self.inventory_locations.filter(storage_type="internal_use", is_active=True).first()
            or self.inventory_locations.first()
        )

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


class BranchWarehouse(TenantModel):
    """Authorized warehouse linked to a branch with operational privileges and priority."""

    branch = models.ForeignKey(
        "tenancy.Branch",
        on_delete=models.CASCADE,
        related_name="branch_warehouses",
    )
    warehouse = models.ForeignKey(
        "tenancy.Warehouse",
        on_delete=models.CASCADE,
        related_name="warehouse_branches",
    )
    is_default = models.BooleanField(
        _("default warehouse for this branch"),
        default=False,
        help_text=_("Primary warehouse used for sales and fulfillment at this branch."),
    )
    can_sell = models.BooleanField(
        _("can sell from this warehouse"),
        default=True,
        help_text=_("Branch can fulfill customer orders and POS sales from this warehouse."),
    )
    can_replenish = models.BooleanField(
        _("can request stock from this warehouse"),
        default=True,
        help_text=_("Branch can request stock replenishment transfers from this warehouse."),
    )
    priority = models.PositiveSmallIntegerField(
        _("fulfillment priority"),
        default=1,
        help_text=_("Lower numbers have higher priority during inventory allocation."),
    )

    class Meta:
        verbose_name = _("branch warehouse mapping")
        verbose_name_plural = _("branch warehouse mappings")
        ordering = ("priority", "warehouse__name")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "branch", "warehouse"],
                name="unique_org_branch_warehouse",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.branch.name} <-> {self.warehouse.name}"


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


class TaxCode(TenantModel):
    """Tax rate specification applicable to products, services, and transactions."""

    code = models.CharField(_("code"), max_length=32, db_index=True)
    name = models.CharField(_("name"), max_length=128)
    rate = models.DecimalField(
        _("rate percentage"),
        max_digits=7,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    is_inclusive = models.BooleanField(_("tax inclusive"), default=False)
    is_default = models.BooleanField(_("default tax code"), default=False)
    is_active = models.BooleanField(_("is active"), default=True)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("tax code")
        verbose_name_plural = _("tax codes")
        ordering = ("code",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_org_tax_code",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active", "code"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.rate}%)"


class Currency(TenantModel):
    """Currency configuration and conversion rate against organization base currency."""

    code = models.CharField(_("currency code"), max_length=3, db_index=True)
    name = models.CharField(_("currency name"), max_length=64)
    symbol = models.CharField(_("symbol"), max_length=8, default="$")
    exchange_rate = models.DecimalField(
        _("exchange rate"),
        max_digits=18,
        decimal_places=6,
        default=Decimal("1.000000"),
    )
    is_base = models.BooleanField(_("base currency"), default=False)
    is_active = models.BooleanField(_("is active"), default=True)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("currency")
        verbose_name_plural = _("currencies")
        ordering = ("code",)
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_org_currency_code",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active", "code"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.symbol})"


class NotificationPreference(TenantModel):
    """Notification preference per channel and event category for the organization."""

    CHANNEL_EMAIL = "email"
    CHANNEL_IN_APP = "in_app"
    CHANNEL_CHOICES = [
        (CHANNEL_EMAIL, _("Email")),
        (CHANNEL_IN_APP, _("In-App")),
    ]

    channel = models.CharField(
        _("channel"),
        max_length=32,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_EMAIL,
    )
    category = models.CharField(_("category"), max_length=64, db_index=True)
    is_enabled = models.BooleanField(_("is enabled"), default=True)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("notification preference")
        verbose_name_plural = _("notification preferences")
        ordering = ("category", "channel")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "category", "channel"],
                name="unique_org_notification_pref",
            ),
        ]

    def __str__(self) -> str:
        state = "enabled" if self.is_enabled else "disabled"
        return f"[{self.organization}] {self.category} via {self.channel}: {state}"


class UserNotificationPreference(TenantModel):
    """Personal notification preferences per user, channel, and category."""

    CHANNEL_EMAIL = NotificationPreference.CHANNEL_EMAIL
    CHANNEL_IN_APP = NotificationPreference.CHANNEL_IN_APP
    CHANNEL_CHOICES = NotificationPreference.CHANNEL_CHOICES

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        verbose_name=_("user"),
    )
    channel = models.CharField(
        _("channel"),
        max_length=32,
        choices=CHANNEL_CHOICES,
        default=CHANNEL_IN_APP,
    )
    category = models.CharField(_("category"), max_length=64, db_index=True)
    is_enabled = models.BooleanField(_("is enabled"), default=True)

    objects: ClassVar[TenantManager[Any]] = TenantManager()
    all_tenants: ClassVar[models.Manager[Any]] = models.Manager()

    class Meta:
        verbose_name = _("user notification preference")
        verbose_name_plural = _("user notification preferences")
        ordering = ("user", "category", "channel")
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user", "category", "channel"],
                name="unique_user_org_notification_pref",
            ),
        ]

    def __str__(self) -> str:
        state = "enabled" if self.is_enabled else "disabled"
        return f"[{self.organization}] User {self.user_id} - {self.category} via {self.channel}: {state}"
