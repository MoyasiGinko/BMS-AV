"""Tests for Superuser / Superadmin hierarchy and dynamic modular roles."""

import pytest
from django.contrib.auth import get_user_model

from apps.core.exceptions import ConflictError, PermissionDeniedError, ValidationError
from apps.core.permissions import get_permissions_by_module, get_user_allowed_branch_ids, has_permission
from apps.tenancy.models import Membership, Role
from apps.tenancy.services import (
    create_custom_role,
    delete_custom_role,
    invite_member,
    provision_organization,
    remove_member,
    switch_organization,
    update_custom_role,
    update_member_role,
)

User = get_user_model()


@pytest.fixture
def tenancy_setup(db):
    owner = User.objects.create_user(email="owner@test.com", password="password123")
    org = provision_organization(
        name="Apex Enterprise",
        slug="apex-ent",
        owner=owner,
        country="BD",
        base_currency="BDT",
    )
    superadmin_role = Role.all_tenants.get(organization=org, name="Superadmin")
    return {
        "user": owner,
        "org": org,
        "superadmin_role": superadmin_role,
    }


def test_superuser_is_highest_authority(db, tenancy_setup):
    """Django is_superuser has blanket permission across all modules without membership."""
    superuser = User.objects.create_superuser(
        email="super@system.local",
        password="rootpassword",
    )
    org = tenancy_setup["org"]

    assert has_permission(superuser, "pos.access", organization=org) is True
    assert has_permission(superuser, "accounting.manage", organization=org) is True
    assert has_permission(superuser, "any.unknown.permission", organization=org) is True
    assert get_user_allowed_branch_ids(superuser, organization=org) is None


def test_superadmin_role_highest_user_authority(db, tenancy_setup):
    """Superadmin role has full access [*], branch unrestricted, and is protected."""
    org = tenancy_setup["org"]
    superadmin_user = User.objects.create_user(
        email="superadmin@test.com",
        password="password123",
    )
    superadmin_role = tenancy_setup["superadmin_role"]
    Membership.all_tenants.create(
        organization=org,
        user=superadmin_user,
        role=superadmin_role,
        is_owner=False,
    )

    assert has_permission(superadmin_user, "sales.invoice_create", organization=org) is True
    assert has_permission(superadmin_user, "accounting.period_close", organization=org) is True
    assert superadmin_role.is_superadmin is True
    assert superadmin_role.has_permission("inventory.adjust") is True
    assert get_user_allowed_branch_ids(superadmin_user, organization=org) is None

    # Cannot delete Superadmin
    with pytest.raises(ValidationError, match="Superadmin role is hardcoded and cannot be deleted"):
        delete_custom_role(role=superadmin_role)

    # Cannot rename away from Superadmin
    with pytest.raises(ValidationError, match="Cannot rename the hardcoded Superadmin role"):
        update_custom_role(
            role=superadmin_role,
            name="Ordinary Role",
            permissions=["pos.access"],
        )


def test_only_software_owner_can_set_or_invite_superadmin(db, tenancy_setup):
    """Only the software owner (superuser) can grant, change, invite, or remove Superadmin."""
    org = tenancy_setup["org"]
    superadmin_role = tenancy_setup["superadmin_role"]

    software_owner = User.objects.create_superuser(
        email="owner@software.local",
        password="rootpassword",
    )
    manager_user = User.objects.create_user(
        email="manager@shop.com",
        password="password123",
    )
    staff_user = User.objects.create_user(
        email="staff@shop.com",
        password="password123",
    )

    dynamic_role = create_custom_role(
        organization=org,
        name="Branch Manager",
        permissions=["pos.*", "inventory.*"],
        actor=software_owner,
    )

    staff_membership = Membership.all_tenants.create(
        organization=org,
        user=staff_user,
        role=dynamic_role,
        is_owner=False,
    )

    # 1. Non-superuser cannot promote someone to Superadmin
    with pytest.raises(PermissionDeniedError, match="Only the software owner"):
        update_member_role(
            membership=staff_membership,
            role=superadmin_role,
            actor=manager_user,
        )

    # 2. Non-superuser cannot invite someone with Superadmin role
    with pytest.raises(PermissionDeniedError, match="Only the software owner"):
        invite_member(
            organization=org,
            email="newcandidate@shop.com",
            role=superadmin_role,
            actor=manager_user,
        )

    # 3. Superuser CAN promote staff to Superadmin
    updated = update_member_role(
        membership=staff_membership,
        role=superadmin_role,
        actor=software_owner,
    )
    assert updated.role == superadmin_role

    # 4. Non-superuser cannot remove a Superadmin
    with pytest.raises(PermissionDeniedError, match="Only the software owner"):
        remove_member(membership=staff_membership, actor=manager_user)


def test_superuser_can_switch_any_organization(db, tenancy_setup):
    """Superuser can switch into any active organization even without direct membership."""
    org = tenancy_setup["org"]
    superuser = User.objects.create_superuser(
        email="superglobal@test.com",
        password="rootpassword",
    )
    session = {}

    switched_org = switch_organization(
        user=superuser,
        organization_id=org.pk,
        session=session,
    )
    assert switched_org == org
    assert session["active_org_id"] == org.pk


def test_dynamic_roles_by_module(db, tenancy_setup):
    """Dynamic roles can be created with module permissions, assigned, updated, and deleted."""
    org = tenancy_setup["org"]
    actor = tenancy_setup["user"]

    # 1. Create dynamic role
    cashier_role = create_custom_role(
        organization=org,
        name="Front Desk Cashier",
        description="POS and sales operations only",
        permissions=["pos.*", "sales.invoice_view"],
        actor=actor,
    )
    assert cashier_role.is_system is False
    assert cashier_role.is_superadmin is False

    # 2. Cannot create duplicate Superadmin
    with pytest.raises(ConflictError, match="reserved as the hardcoded authority role"):
        create_custom_role(
            organization=org,
            name="Superadmin",
            permissions=["*"],
            actor=actor,
        )

    # 3. Dynamic permissions check
    cashier_user = User.objects.create_user(
        email="cashier1@test.com",
        password="password123",
    )
    membership = Membership.all_tenants.create(
        organization=org,
        user=cashier_user,
        role=cashier_role,
        is_owner=False,
    )

    assert has_permission(cashier_user, "pos.access", organization=org) is True
    assert has_permission(cashier_user, "pos.refund", organization=org) is True
    assert has_permission(cashier_user, "sales.invoice_view", organization=org) is True
    assert has_permission(cashier_user, "accounting.manage", organization=org) is False

    # 4. Cannot delete role while active members are assigned
    with pytest.raises(ValidationError, match="Cannot delete role with assigned active members"):
        delete_custom_role(role=cashier_role)

    # 5. Delete after reassigning/removing member
    membership.delete()
    delete_custom_role(role=cashier_role)
    assert not Role.all_tenants.filter(pk=cashier_role.pk).exists()


def test_get_permissions_by_module_catalog():
    """Module permission catalog returns grouped permissions with titles and descriptions."""
    catalog = get_permissions_by_module()
    assert "pos" in catalog
    assert "sales" in catalog
    assert "accounting" in catalog
    assert "settings" in catalog
    assert len(catalog["pos"]["permissions"]) > 0
    assert any(p.code == "pos.access" for p in catalog["pos"]["permissions"])
