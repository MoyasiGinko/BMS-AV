"""Tenancy selectors for querying organizations, members, branches, and roles."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet

from apps.tenancy.models import (
    Branch,
    Invitation,
    Membership,
    Organization,
    OrganizationSettings,
    Role,
    Warehouse,
)


def list_user_organizations(*, user: AbstractBaseUser) -> QuerySet[Organization]:
    """Return all active organizations the user belongs to."""
    org_ids = Membership.all_tenants.filter(
        user=user,
        status=Membership.STATUS_ACTIVE,
    ).values_list("organization_id", flat=True)
    return Organization.objects.filter(id__in=org_ids, is_active=True).order_by("name")


def get_user_membership(*, user: AbstractBaseUser, organization_id: int) -> Membership | None:
    """Return active membership of user in specific organization."""
    return (
        Membership.all_tenants.filter(
            user=user,
            organization_id=organization_id,
            status=Membership.STATUS_ACTIVE,
        )
        .select_related("role", "organization")
        .first()
    )


def list_organization_members(*, organization_id: int) -> QuerySet[Membership]:
    """Return all members belonging to an organization."""
    return (
        Membership.all_tenants.filter(organization_id=organization_id)
        .select_related("user", "role")
        .order_by("user__email")
    )


def list_organization_branches(*, organization_id: int) -> QuerySet[Branch]:
    """Return all branches of an organization."""
    return Branch.all_tenants.filter(organization_id=organization_id, is_active=True).order_by("name")


def list_organization_warehouses(*, organization_id: int) -> QuerySet[Warehouse]:
    """Return all warehouses belonging to an organization."""
    return (
        Warehouse.all_tenants.filter(organization_id=organization_id, is_active=True)
        .select_related("branch")
        .order_by("name")
    )


def get_organization_settings(*, organization_id: int) -> OrganizationSettings | None:
    """Return organization business settings."""
    return OrganizationSettings.all_tenants.filter(organization_id=organization_id).first()


def list_organization_roles(*, organization_id: int) -> QuerySet[Role]:
    """Return all roles defined for an organization."""
    return Role.all_tenants.filter(organization_id=organization_id).order_by("name")


def get_invitation_by_token(*, token: str) -> Invitation | None:
    """Look up an invitation by its secret token."""
    return Invitation.all_tenants.filter(token=token).select_related("organization", "role").first()
