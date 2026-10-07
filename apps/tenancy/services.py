"""Tenancy domain services: organization provisioning, member invitation, role seeding."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.events import publish
from apps.core.exceptions import ConflictError, RecordNotFoundError, ValidationError
from apps.core.hooks import run_provisioning_hooks
from apps.core.models import NumberSequence
from apps.tenancy.models import (
    Branch,
    Currency,
    Department,
    Invitation,
    Membership,
    NotificationPreference,
    Organization,
    OrganizationSettings,
    Role,
    TaxCode,
    Warehouse,
)

logger = logging.getLogger(__name__)

DEFAULT_ROLES_PERMISSIONS: dict[str, list[str]] = {
    "Owner": ["*"],
    "Admin": [
        "catalog.*",
        "inventory.*",
        "sales.*",
        "purchasing.*",
        "customers.*",
        "accounting.*",
        "pos.*",
        "hr.*",
        "payroll.*",
        "reports.*",
        "settings.manage",
        "users.manage",
        "integrations.manage",
    ],
    "Manager": [
        "catalog.*",
        "inventory.*",
        "sales.*",
        "purchasing.*",
        "customers.*",
        "accounting.view",
        "pos.*",
        "hr.view",
        "reports.*",
    ],
    "Accountant": [
        "accounting.*",
        "sales.view",
        "purchasing.view",
        "reports.*",
        "customers.view",
        "payroll.view",
    ],
    "Cashier": [
        "pos.*",
        "sales.view",
        "sales.create",
        "customers.view",
        "catalog.view",
    ],
    "HR": [
        "hr.*",
        "payroll.*",
        "reports.view",
    ],
    "Viewer": [
        "catalog.view",
        "inventory.view",
        "sales.view",
        "customers.view",
        "reports.view",
    ],
}


@transaction.atomic
def seed_default_roles(*, organization: Organization) -> dict[str, Role]:
    """Seed system roles and permission codes for an organization."""
    created_roles: dict[str, Role] = {}
    for role_name, perms in DEFAULT_ROLES_PERMISSIONS.items():
        role, _ = Role.all_tenants.get_or_create(
            organization=organization,
            name=role_name,
            defaults={
                "description": f"Standard {role_name} role",
                "permissions": perms,
                "is_system": True,
            },
        )
        created_roles[role_name] = role
    return created_roles


DEFAULT_SEQUENCES: list[dict[str, Any]] = [
    {"name": "Invoices", "prefix": "INV-", "padding": 5},
    {"name": "Quotes", "prefix": "QTE-", "padding": 5},
    {"name": "Orders", "prefix": "ORD-", "padding": 5},
    {"name": "Purchase Orders", "prefix": "PO-", "padding": 5},
    {"name": "Bills", "prefix": "BIL-", "padding": 5},
    {"name": "Payments", "prefix": "PAY-", "padding": 5},
    {"name": "Receipts", "prefix": "RCT-", "padding": 5},
    {"name": "Journal Entries", "prefix": "JE-", "padding": 5},
]


@dataclass
class ProvisioningContext:
    """Carries newly provisioned tenant objects to registered module hooks."""

    organization: Organization
    owner: AbstractBaseUser
    roles: dict[str, Role]
    headquarters_branch: Branch
    default_warehouse: Warehouse
    settings: OrganizationSettings
    sequences: dict[str, NumberSequence] = field(default_factory=dict)
    invitations: list[Invitation] = field(default_factory=list)
    extra_data: dict[str, Any] = field(default_factory=dict)


@transaction.atomic
def invite_member(
    *,
    organization: Organization,
    email: str,
    role: Role,
    actor: AbstractBaseUser,
    days_valid: int = 7,
) -> Invitation:
    """Send an invitation email to join an organization with a specific role."""
    normalized_email = email.lower().strip()

    # Check existing active membership
    if Membership.all_tenants.filter(organization=organization, user__email=normalized_email).exists():
        raise ConflictError(_("A user with this email is already a member of this organization."))

    expires_at = timezone.now() + datetime.timedelta(days=days_valid)

    # Invalidate any prior pending invitations for this email
    Invitation.all_tenants.filter(
        organization=organization,
        email=normalized_email,
        status=Invitation.STATUS_PENDING,
    ).update(status=Invitation.STATUS_REVOKED)

    invitation = Invitation.all_tenants.create(
        organization=organization,
        email=normalized_email,
        role=role,
        expires_at=expires_at,
        created_by=actor,
    )

    # Send invitation email
    try:
        send_mail(
            subject=_("Invitation to join %(org_name)s on Business OS") % {"org_name": organization.name},
            message=_(
                "You have been invited to join %(org_name)s as %(role_name)s.\n"
                "Use the token below to accept your invitation:\n%(token)s"
            )
            % {
                "org_name": organization.name,
                "role_name": role.name,
                "token": invitation.token,
            },
            from_email=None,
            recipient_list=[normalized_email],
        )
    except Exception:
        logger.exception("Failed to send invitation email to %s", normalized_email)

    return invitation


@transaction.atomic
def provision_organization(
    *,
    name: str,
    slug: str,
    owner: AbstractBaseUser,
    plan: str | None = "starter",
    base_currency: str = "USD",
    country: str = "",
    timezone_str: str = "UTC",
    fiscal_year_start: int = 1,
    date_format: str = "Y-m-d",
    branch_name: str = "Main Branch",
    branch_code: str = "MAIN",
    warehouse_name: str = "Main Warehouse",
    warehouse_code: str = "WH-MAIN",
    team_invites: list[str] | list[dict[str, str]] | None = None,
    extra_data: dict[str, Any] | None = None,
    actor: Any = None,
) -> Organization:
    """Transactionally provision a complete tenant organization workspace."""
    clean_slug = slug.strip().lower()
    if Organization.objects.filter(slug=clean_slug).exists():
        raise ConflictError(_("An organization with this slug already exists."))

    org = Organization.objects.create(
        name=name.strip(),
        slug=clean_slug,
        base_currency=base_currency.upper(),
        country=country.upper() if country else "",
        timezone=timezone_str,
        fiscal_year_start=fiscal_year_start,
        date_format=date_format,
    )

    # 1. Seed system roles
    roles = seed_default_roles(organization=org)

    # 2. Assign owner membership
    Membership.all_tenants.create(
        organization=org,
        user=owner,
        role=roles["Owner"],
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    # 3. Seed headquarters branch
    branch = Branch.all_tenants.create(
        organization=org,
        name=branch_name.strip() or "Main Branch",
        code=branch_code.strip() or "MAIN",
        is_headquarters=True,
    )

    # 4. Seed default warehouse
    warehouse = Warehouse.all_tenants.create(
        organization=org,
        branch=branch,
        name=warehouse_name.strip() or "Main Warehouse",
        code=warehouse_code.strip() or "WH-MAIN",
        is_default=True,
    )

    # 5. Seed organization settings
    settings_obj = OrganizationSettings.all_tenants.create(
        organization=org,
    )

    # 6. Seed document number sequences
    created_sequences: dict[str, NumberSequence] = {}
    for seq_def in DEFAULT_SEQUENCES:
        seq = NumberSequence.all_tenants.create(
            organization=org,
            name=seq_def["name"],
            prefix=seq_def["prefix"],
            padding=seq_def["padding"],
            next_number=1,
            reset_frequency=NumberSequence.RESET_NEVER,
        )
        created_sequences[seq_def["name"]] = seq

    # 6b. Seed base currency & default tax code
    Currency.objects.get_or_create(
        organization=org,
        code=base_currency.upper(),
        defaults={
            "name": f"{base_currency.upper()} Base Currency",
            "symbol": "$",
            "exchange_rate": Decimal("1.000000"),
            "is_base": True,
            "is_active": True,
            "created_by": owner,
        },
    )
    TaxCode.objects.get_or_create(
        organization=org,
        code="STANDARD",
        defaults={
            "name": "Standard Tax",
            "rate": Decimal("0.0000"),
            "is_inclusive": False,
            "is_default": True,
            "is_active": True,
            "created_by": owner,
        },
    )

    # 7. Process initial team invitations
    invitations: list[Invitation] = []
    if team_invites:
        staff_role = roles.get("Staff") or roles.get("Viewer") or roles["Owner"]
        for invite_item in team_invites:
            if isinstance(invite_item, str):
                target_email = invite_item.strip()
                target_role = staff_role
            elif isinstance(invite_item, dict):
                target_email = invite_item.get("email", "").strip()
                role_name = invite_item.get("role", "Staff")
                target_role = roles.get(role_name, staff_role)
            else:
                continue

            if target_email and target_email != getattr(owner, "email", ""):
                try:
                    inv = invite_member(
                        organization=org,
                        email=target_email,
                        role=target_role,
                        actor=owner,
                    )
                    invitations.append(inv)
                except Exception as exc:
                    logger.warning("Could not invite %s during provisioning: %s", target_email, exc)

    # 8. Assemble context and execute downstream module hooks
    combined_extra = extra_data.copy() if extra_data else {}
    if plan:
        combined_extra["plan_slug"] = plan
    ctx = ProvisioningContext(
        organization=org,
        owner=owner,
        roles=roles,
        headquarters_branch=branch,
        default_warehouse=warehouse,
        settings=settings_obj,
        sequences=created_sequences,
        invitations=invitations,
        extra_data=combined_extra,
    )
    run_provisioning_hooks(ctx)

    # 9. Publish domain event
    publish(
        "organization.provisioned",
        organization_id=org.pk,
        actor_id=getattr(actor or owner, "pk", None),
        payload={
            "organization_id": org.pk,
            "slug": org.slug,
            "name": org.name,
            "owner_id": getattr(owner, "pk", None),
            "plan_slug": plan,
        },
    )

    logger.info("Successfully provisioned organization '%s' (%s)", org.name, org.slug)
    return org


def create_organization(
    *,
    name: str,
    slug: str,
    owner: AbstractBaseUser,
    plan: str | None = None,
    base_currency: str = "USD",
    country: str = "",
    timezone_str: str = "UTC",
    actor: Any = None,
    **kwargs: Any,
) -> Organization:
    """Provision a complete new organization workspace."""
    return provision_organization(
        name=name,
        slug=slug,
        owner=owner,
        plan=plan,
        base_currency=base_currency,
        country=country,
        timezone_str=timezone_str,
        actor=actor,
        **kwargs,
    )


@transaction.atomic
def accept_invitation(*, token: str, user: AbstractBaseUser) -> Membership:
    """Accept an invitation by token and create active organization membership."""
    invitation = Invitation.all_tenants.select_for_update().filter(token=token).first()
    if invitation is None:
        raise RecordNotFoundError(_("Invitation not found."))

    if not invitation.is_valid:
        raise ValidationError(_("This invitation has expired or is no longer valid."))

    # Check if user email matches invitation email (or allow user to accept)
    membership, created = Membership.all_tenants.get_or_create(
        organization=invitation.organization,
        user=user,
        defaults={
            "role": invitation.role,
            "is_owner": False,
            "status": Membership.STATUS_ACTIVE,
        },
    )
    if not created:
        membership.role = invitation.role
        membership.status = Membership.STATUS_ACTIVE
        membership.save(update_fields=["role", "status", "updated_at"])

    invitation.status = Invitation.STATUS_ACCEPTED
    invitation.save(update_fields=["status", "updated_at"])

    return membership


def switch_organization(*, user: AbstractBaseUser, organization_id: int, session: Any) -> Organization:
    """Verify membership and switch the active organization stored in the session."""
    membership = (
        Membership.all_tenants.filter(
            user=user,
            organization_id=organization_id,
            status=Membership.STATUS_ACTIVE,
            organization__is_active=True,
        )
        .select_related("organization")
        .first()
    )
    if membership is None or membership.organization is None:
        raise ValidationError(_("You are not an active member of this organization."))

    session["active_org_id"] = organization_id
    if hasattr(session, "modified"):
        session.modified = True
    return membership.organization


# ---------------------------------------------------------------------------
# Settings CRUD Services
# ---------------------------------------------------------------------------


@transaction.atomic
def update_organization_profile(
    *,
    organization: Organization,
    name: str,
    base_currency: str = "USD",
    country: str = "",
    timezone_str: str = "UTC",
    fiscal_year_start: int = 1,
    date_format: str = "Y-m-d",
    actor: Any = None,
) -> Organization:
    """Update primary organization profile details."""
    organization.name = name.strip()
    organization.base_currency = base_currency.strip().upper()
    organization.country = country.strip().upper()
    organization.timezone = timezone_str.strip()
    organization.fiscal_year_start = max(1, min(12, fiscal_year_start))
    organization.date_format = date_format.strip()
    organization.save(
        update_fields=[
            "name",
            "base_currency",
            "country",
            "timezone",
            "fiscal_year_start",
            "date_format",
            "updated_at",
        ]
    )
    return organization


@transaction.atomic
def update_organization_settings(
    *,
    organization: Organization,
    allow_negative_stock: bool = False,
    costing_method: str = "weighted_average",
    tax_inclusive_pricing: bool = False,
    actor: Any = None,
) -> OrganizationSettings:
    """Update tenant-wide operations settings."""
    settings_obj, _ = OrganizationSettings.all_tenants.select_for_update().get_or_create(
        organization=organization
    )
    settings_obj.allow_negative_stock = allow_negative_stock
    settings_obj.costing_method = costing_method
    settings_obj.tax_inclusive_pricing = tax_inclusive_pricing
    settings_obj.save(
        update_fields=["allow_negative_stock", "costing_method", "tax_inclusive_pricing", "updated_at"]
    )
    return settings_obj


@transaction.atomic
def create_branch(
    *,
    organization: Organization,
    name: str,
    code: str = "",
    address: str = "",
    phone: str = "",
    is_headquarters: bool = False,
    actor: Any = None,
) -> Branch:
    """Create a new branch within organization."""
    if is_headquarters:
        Branch.all_tenants.filter(organization=organization, is_headquarters=True).update(
            is_headquarters=False
        )
    return Branch.objects.create(
        organization=organization,
        name=name.strip(),
        code=code.strip().upper(),
        address=address.strip(),
        phone=phone.strip(),
        is_headquarters=is_headquarters,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def update_branch(
    *,
    branch: Branch,
    name: str,
    code: str = "",
    address: str = "",
    phone: str = "",
    is_headquarters: bool = False,
    is_active: bool = True,
    actor: Any = None,
) -> Branch:
    """Update existing branch properties."""
    if is_headquarters and not branch.is_headquarters:
        Branch.all_tenants.filter(organization=branch.organization, is_headquarters=True).update(
            is_headquarters=False
        )
    branch.name = name.strip()
    branch.code = code.strip().upper()
    branch.address = address.strip()
    branch.phone = phone.strip()
    branch.is_headquarters = is_headquarters
    branch.is_active = is_active
    branch.save()
    return branch


@transaction.atomic
def delete_branch(*, branch: Branch, actor: Any = None) -> None:
    """Delete branch with safety validation against headquarters or linked warehouses."""
    if branch.is_headquarters:
        raise ValidationError(_("Cannot delete headquarters branch."))
    if branch.warehouses.exists():
        raise ValidationError(_("Cannot delete branch that has associated warehouses."))
    branch.delete()


@transaction.atomic
def create_warehouse(
    *,
    organization: Organization,
    branch: Branch,
    name: str,
    code: str = "",
    is_default: bool = False,
    actor: Any = None,
) -> Warehouse:
    """Create a storage warehouse attached to a branch."""
    if is_default:
        Warehouse.all_tenants.filter(organization=organization, is_default=True).update(is_default=False)
    return Warehouse.objects.create(
        organization=organization,
        branch=branch,
        name=name.strip(),
        code=code.strip().upper(),
        is_default=is_default,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def update_warehouse(
    *,
    warehouse: Warehouse,
    name: str,
    branch: Branch,
    code: str = "",
    is_default: bool = False,
    is_active: bool = True,
    actor: Any = None,
) -> Warehouse:
    """Update warehouse attributes."""
    if is_default and not warehouse.is_default:
        Warehouse.all_tenants.filter(organization=warehouse.organization, is_default=True).update(
            is_default=False
        )
    warehouse.name = name.strip()
    warehouse.branch = branch
    warehouse.code = code.strip().upper()
    warehouse.is_default = is_default
    warehouse.is_active = is_active
    warehouse.save()
    return warehouse


@transaction.atomic
def delete_warehouse(*, warehouse: Warehouse, actor: Any = None) -> None:
    """Delete warehouse with safety guard against default warehouse removal."""
    if warehouse.is_default:
        raise ValidationError(_("Cannot delete default warehouse."))
    warehouse.delete()


@transaction.atomic
def create_department(
    *,
    organization: Organization,
    name: str,
    code: str = "",
    parent: Department | None = None,
    actor: Any = None,
) -> Department:
    """Create a new organizational department."""
    return Department.objects.create(
        organization=organization,
        name=name.strip(),
        code=code.strip().upper(),
        parent=parent,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def update_department(
    *,
    department: Department,
    name: str,
    code: str = "",
    parent: Department | None = None,
    is_active: bool = True,
    actor: Any = None,
) -> Department:
    """Update department properties."""
    if parent and parent.pk == department.pk:
        raise ValidationError(_("Department cannot be its own parent."))
    department.name = name.strip()
    department.code = code.strip().upper()
    department.parent = parent
    department.is_active = is_active
    department.save()
    return department


@transaction.atomic
def delete_department(*, department: Department, actor: Any = None) -> None:
    """Delete department record."""
    department.delete()


@transaction.atomic
def create_custom_role(
    *,
    organization: Organization,
    name: str,
    description: str = "",
    permissions: list[str] | None = None,
    actor: Any = None,
) -> Role:
    """Create a user-defined custom role with specified permission codes."""
    if Role.all_tenants.filter(organization=organization, name__iexact=name.strip()).exists():
        raise ConflictError(_("A role with name '%(name)s' already exists.") % {"name": name})
    return Role.objects.create(
        organization=organization,
        name=name.strip(),
        description=description.strip(),
        permissions=permissions or [],
        is_system=False,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def update_custom_role(
    *,
    role: Role,
    name: str,
    description: str = "",
    permissions: list[str] | None = None,
    actor: Any = None,
) -> Role:
    """Update role details and permissions."""
    if role.is_system and role.name != name.strip():
        raise ValidationError(_("Cannot rename system roles."))
    role.name = name.strip()
    role.description = description.strip()
    if not role.is_system or role.name != "Owner":
        role.permissions = permissions or []
    role.save()
    return role


@transaction.atomic
def delete_custom_role(*, role: Role, actor: Any = None) -> None:
    """Delete custom role, guarding against system roles and roles in active use."""
    if role.is_system:
        raise ValidationError(_("System default roles cannot be deleted."))
    if role.memberships.exists():
        raise ValidationError(_("Cannot delete role with assigned active members."))
    role.delete()


@transaction.atomic
def revoke_invitation(*, invitation: Invitation, actor: Any = None) -> None:
    """Mark an active invitation as revoked."""
    invitation.status = Invitation.STATUS_REVOKED
    invitation.save(update_fields=["status", "updated_at"])


@transaction.atomic
def update_member_role(
    *,
    membership: Membership,
    role: Role,
    status: str = Membership.STATUS_ACTIVE,
    actor: Any = None,
) -> Membership:
    """Change a member's role or status."""
    if membership.is_owner and status != Membership.STATUS_ACTIVE:
        raise ValidationError(_("Organization owner cannot be suspended."))
    membership.role = role
    membership.status = status
    membership.save(update_fields=["role", "status", "updated_at"])
    return membership


@transaction.atomic
def remove_member(*, membership: Membership, actor: Any = None) -> None:
    """Remove member from organization, preventing owner removal."""
    if membership.is_owner:
        raise ValidationError(_("Organization owner cannot be removed."))
    membership.delete()


@transaction.atomic
def update_number_sequence(
    *,
    sequence: NumberSequence,
    prefix: str = "",
    suffix: str = "",
    next_number: int = 1,
    padding: int = 5,
    reset_frequency: str = NumberSequence.RESET_NEVER,
    actor: Any = None,
) -> NumberSequence:
    """Update document numbering format."""
    sequence.prefix = prefix.strip()
    sequence.suffix = suffix.strip()
    sequence.next_number = max(1, next_number)
    sequence.padding = max(1, min(10, padding))
    sequence.reset_frequency = reset_frequency
    sequence.save()
    return sequence


@transaction.atomic
def create_tax_code(
    *,
    organization: Organization,
    code: str,
    name: str,
    rate: Decimal,
    is_inclusive: bool = False,
    is_default: bool = False,
    actor: Any = None,
) -> TaxCode:
    """Create a new tax code rate."""
    if is_default:
        TaxCode.all_tenants.filter(organization=organization, is_default=True).update(is_default=False)
    return TaxCode.objects.create(
        organization=organization,
        code=code.strip().upper(),
        name=name.strip(),
        rate=rate,
        is_inclusive=is_inclusive,
        is_default=is_default,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def update_tax_code(
    *,
    tax_code: TaxCode,
    name: str,
    rate: Decimal,
    is_inclusive: bool = False,
    is_default: bool = False,
    is_active: bool = True,
    actor: Any = None,
) -> TaxCode:
    """Update tax code rate and configuration."""
    if is_default and not tax_code.is_default:
        TaxCode.all_tenants.filter(organization=tax_code.organization, is_default=True).update(
            is_default=False
        )
    tax_code.name = name.strip()
    tax_code.rate = rate
    tax_code.is_inclusive = is_inclusive
    tax_code.is_default = is_default
    tax_code.is_active = is_active
    tax_code.save()
    return tax_code


@transaction.atomic
def delete_tax_code(*, tax_code: TaxCode, actor: Any = None) -> None:
    """Delete tax code record, disallowing removal if set as default."""
    if tax_code.is_default:
        raise ValidationError(_("Cannot delete default tax code."))
    tax_code.delete()


@transaction.atomic
def create_currency(
    *,
    organization: Organization,
    code: str,
    name: str,
    symbol: str = "$",
    exchange_rate: Decimal = Decimal("1.000000"),
    is_base: bool = False,
    actor: Any = None,
) -> Currency:
    """Create currency record and configure base currency."""
    if is_base:
        Currency.all_tenants.filter(organization=organization, is_base=True).update(is_base=False)
        organization.base_currency = code.strip().upper()
        organization.save(update_fields=["base_currency", "updated_at"])
    return Currency.objects.create(
        organization=organization,
        code=code.strip().upper(),
        name=name.strip(),
        symbol=symbol.strip(),
        exchange_rate=exchange_rate,
        is_base=is_base,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def update_currency(
    *,
    currency: Currency,
    name: str,
    symbol: str,
    exchange_rate: Decimal,
    is_base: bool = False,
    is_active: bool = True,
    actor: Any = None,
) -> Currency:
    """Update currency rate and settings."""
    if is_base and not currency.is_base:
        Currency.all_tenants.filter(organization=currency.organization, is_base=True).update(is_base=False)
        currency.organization.base_currency = currency.code
        currency.organization.save(update_fields=["base_currency", "updated_at"])
    currency.name = name.strip()
    currency.symbol = symbol.strip()
    currency.exchange_rate = exchange_rate
    currency.is_base = is_base
    currency.is_active = is_active
    currency.save()
    return currency


@transaction.atomic
def delete_currency(*, currency: Currency, actor: Any = None) -> None:
    """Delete currency, preventing deletion of organization base currency."""
    if currency.is_base:
        raise ValidationError(_("Cannot delete organization base currency."))
    currency.delete()


@transaction.atomic
def update_notification_preference(
    *,
    organization: Organization,
    category: str,
    channel: str,
    is_enabled: bool,
    actor: Any = None,
) -> NotificationPreference:
    """Configure or toggle a channel notification preference."""
    pref, _ = NotificationPreference.all_tenants.select_for_update().get_or_create(
        organization=organization,
        category=category.strip(),
        channel=channel.strip(),
        defaults={"is_enabled": is_enabled},
    )
    pref.is_enabled = is_enabled
    pref.save(update_fields=["is_enabled", "updated_at"])
    return pref
