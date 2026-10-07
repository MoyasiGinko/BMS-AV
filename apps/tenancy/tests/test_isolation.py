import pytest
from django.contrib.auth import get_user_model

from apps.core.tenant_context import tenant_context
from apps.tenancy.models import (
    Branch,
    Invitation,
    Membership,
    Role,
    Warehouse,
)
from apps.tenancy.services import create_organization, invite_member

User = get_user_model()


@pytest.mark.django_db
def test_two_orgs_fully_isolated() -> None:
    # 1. Create two separate organizations with distinct owners
    user_a = User.objects.create_user(email="owner_a@example.com", password="SecretPassword123!")
    user_b = User.objects.create_user(email="owner_b@example.com", password="SecretPassword123!")

    org_a = create_organization(name="Acme Corp", slug="acme", owner=user_a)
    org_b = create_organization(name="Beta Industries", slug="beta", owner=user_b)

    # 2. Add extra tenant-owned entities in each org
    role_a = Role.all_tenants.filter(organization=org_a, name="Manager").first()
    role_b = Role.all_tenants.filter(organization=org_b, name="Manager").first()
    assert role_a is not None
    assert role_b is not None

    invite_member(organization=org_a, email="invite_a@example.com", role=role_a, actor=user_a)
    invite_member(organization=org_b, email="invite_b@example.com", role=role_b, actor=user_b)

    branch_a_extra = Branch.all_tenants.create(organization=org_a, name="Acme North", code="ACME-N")
    branch_b_extra = Branch.all_tenants.create(organization=org_b, name="Beta South", code="BETA-S")

    Warehouse.all_tenants.create(organization=org_a, branch=branch_a_extra, name="Acme Depot", code="WH-ACME")
    Warehouse.all_tenants.create(organization=org_b, branch=branch_b_extra, name="Beta Depot", code="WH-BETA")

    # 3. Verify Isolation in Org A
    with tenant_context(org_a):
        # Branches
        branch_ids = set(Branch.objects.values_list("id", flat=True))
        assert branch_a_extra.pk in branch_ids
        assert branch_b_extra.pk not in branch_ids
        for b in Branch.objects.all():
            assert b.organization_id == org_a.pk

        # Warehouses
        for w in Warehouse.objects.all():
            assert w.organization_id == org_a.pk
            assert "Beta" not in w.name

        # Memberships
        member_emails = set(Membership.objects.values_list("user__email", flat=True))
        assert "owner_a@example.com" in member_emails
        assert "owner_b@example.com" not in member_emails

        # Roles
        for r in Role.objects.all():
            assert r.organization_id == org_a.pk

        # Invitations
        for inv in Invitation.objects.all():
            assert inv.organization_id == org_a.pk
            assert inv.email == "invite_a@example.com"

    # 4. Verify Isolation in Org B
    with tenant_context(org_b):
        # Branches
        branch_ids = set(Branch.objects.values_list("id", flat=True))
        assert branch_b_extra.pk in branch_ids
        assert branch_a_extra.pk not in branch_ids
        for b in Branch.objects.all():
            assert b.organization_id == org_b.pk

        # Warehouses
        for w in Warehouse.objects.all():
            assert w.organization_id == org_b.pk
            assert "Acme" not in w.name

        # Memberships
        member_emails = set(Membership.objects.values_list("user__email", flat=True))
        assert "owner_b@example.com" in member_emails
        assert "owner_a@example.com" not in member_emails

        # Roles
        for r in Role.objects.all():
            assert r.organization_id == org_b.pk

        # Invitations
        for inv in Invitation.objects.all():
            assert inv.organization_id == org_b.pk
            assert inv.email == "invite_b@example.com"

    # 5. Outside of any tenant context: scoped managers return nothing
    assert Branch.objects.count() == 0
    assert Warehouse.objects.count() == 0
    assert Membership.objects.count() == 0
    assert Role.objects.count() == 0
    assert Invitation.objects.count() == 0

    # 6. Unscoped all_tenants manager sees all across the platform
    assert Branch.all_tenants.count() == 4  # 2 headquarters + 2 extra
    assert Warehouse.all_tenants.count() == 4
