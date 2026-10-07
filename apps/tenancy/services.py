"""Tenancy domain services: organization provisioning, member invitation, role seeding."""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
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
    Invitation,
    Membership,
    Organization,
    OrganizationSettings,
    Role,
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
