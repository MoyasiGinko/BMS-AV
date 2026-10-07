"""Tenancy selectors for querying organizations, members, branches, and roles."""

from __future__ import annotations

import uuid
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import QuerySet

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


def list_organization_invitations(*, organization_id: int, pending_only: bool = True) -> QuerySet[Invitation]:
    """Return all pending (or all) invitations for an organization."""
    qs = Invitation.all_tenants.filter(organization_id=organization_id)
    if pending_only:
        qs = qs.filter(status=Invitation.STATUS_PENDING)
    return qs.select_related("role").order_by("-created_at")


def list_organization_departments(*, organization_id: int) -> QuerySet[Department]:
    """Return all departments belonging to an organization."""
    return (
        Department.all_tenants.filter(organization_id=organization_id)
        .select_related("parent")
        .order_by("name")
    )


def list_organization_tax_codes(*, organization_id: int) -> QuerySet[TaxCode]:
    """Return all tax codes defined for an organization."""
    return TaxCode.all_tenants.filter(organization_id=organization_id).order_by("code")


def list_organization_currencies(*, organization_id: int) -> QuerySet[Currency]:
    """Return all currency configurations for an organization."""
    return Currency.all_tenants.filter(organization_id=organization_id).order_by("-is_base", "code")


def list_organization_notification_preferences(*, organization_id: int) -> QuerySet[NotificationPreference]:
    """Return notification preferences configured for the organization."""
    return NotificationPreference.all_tenants.filter(organization_id=organization_id).order_by("category")


def list_organization_number_sequences(*, organization_id: int) -> QuerySet[NumberSequence]:
    """Return document number sequences for the organization."""
    return NumberSequence.all_tenants.filter(organization_id=organization_id).order_by("name")


def _filter_by_id_or_uuid(qs: QuerySet[Any], ident: Any) -> Any | None:
    ident_str = str(ident)
    try:
        val = uuid.UUID(ident_str)
        return qs.filter(public_id=val).first()
    except ValueError, AttributeError:
        pass
    if ident_str.isdigit():
        return qs.filter(id=int(ident_str)).first()
    return None


def get_branch_by_id(*, organization_id: int, branch_id: Any) -> Branch | None:
    """Retrieve branch by public_id or integer PK within organization."""
    qs = Branch.all_tenants.filter(organization_id=organization_id)
    return _filter_by_id_or_uuid(qs, branch_id)


def get_warehouse_by_id(*, organization_id: int, warehouse_id: Any) -> Warehouse | None:
    """Retrieve warehouse by public_id or integer PK within organization."""
    qs = Warehouse.all_tenants.filter(organization_id=organization_id).select_related("branch")
    return _filter_by_id_or_uuid(qs, warehouse_id)


def get_department_by_id(*, organization_id: int, department_id: Any) -> Department | None:
    """Retrieve department by public_id or integer PK within organization."""
    qs = Department.all_tenants.filter(organization_id=organization_id).select_related("parent")
    return _filter_by_id_or_uuid(qs, department_id)


def get_role_by_id(*, organization_id: int, role_id: Any) -> Role | None:
    """Retrieve role by public_id or integer PK within organization."""
    qs = Role.all_tenants.filter(organization_id=organization_id)
    return _filter_by_id_or_uuid(qs, role_id)


def get_membership_by_id(*, organization_id: int, membership_id: Any) -> Membership | None:
    """Retrieve membership by public_id or integer PK within organization."""
    qs = Membership.all_tenants.filter(organization_id=organization_id).select_related("user", "role")
    return _filter_by_id_or_uuid(qs, membership_id)


def get_tax_code_by_id(*, organization_id: int, tax_code_id: Any) -> TaxCode | None:
    """Retrieve tax code by public_id or integer PK within organization."""
    qs = TaxCode.all_tenants.filter(organization_id=organization_id)
    return _filter_by_id_or_uuid(qs, tax_code_id)


def get_currency_by_id(*, organization_id: int, currency_id: Any) -> Currency | None:
    """Retrieve currency by public_id or integer PK within organization."""
    qs = Currency.all_tenants.filter(organization_id=organization_id)
    return _filter_by_id_or_uuid(qs, currency_id)


def get_number_sequence_by_id(*, organization_id: int, sequence_id: Any) -> NumberSequence | None:
    """Retrieve number sequence by public_id or integer PK within organization."""
    qs = NumberSequence.all_tenants.filter(organization_id=organization_id)
    return _filter_by_id_or_uuid(qs, sequence_id)
