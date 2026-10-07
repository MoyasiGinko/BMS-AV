"""Tenancy domain services: organization provisioning, member invitation, role seeding."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.exceptions import ConflictError, RecordNotFoundError, ValidationError
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


@transaction.atomic
def create_organization(
    *,
    name: str,
    slug: str,
    owner: AbstractBaseUser,
    base_currency: str = "USD",
    country: str = "",
    timezone_str: str = "UTC",
    actor: Any = None,
) -> Organization:
    """Provision a complete new organization workspace with default roles, branch, and warehouse."""
    if Organization.objects.filter(slug=slug).exists():
        raise ConflictError(_("An organization with this slug already exists."))

    org = Organization.objects.create(
        name=name,
        slug=slug,
        base_currency=base_currency,
        country=country,
        timezone=timezone_str,
    )

    # 1. Seed default roles
    roles = seed_default_roles(organization=org)

    # 2. Seed headquarters branch
    branch = Branch.all_tenants.create(
        organization=org,
        name="Main Branch",
        code="MAIN",
        is_headquarters=True,
    )

    # 3. Seed default warehouse
    Warehouse.all_tenants.create(
        organization=org,
        branch=branch,
        name="Main Warehouse",
        code="WH-MAIN",
        is_default=True,
    )

    # 4. Seed default settings
    OrganizationSettings.all_tenants.create(
        organization=org,
    )

    # 5. Assign owner membership
    Membership.all_tenants.create(
        organization=org,
        user=owner,
        role=roles["Owner"],
        is_owner=True,
        status=Membership.STATUS_ACTIVE,
    )

    return org


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
