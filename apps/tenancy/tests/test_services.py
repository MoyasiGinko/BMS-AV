import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from apps.core.exceptions import ConflictError, ValidationError
from apps.tenancy.models import (
    Branch,
    Invitation,
    Membership,
    Organization,
    OrganizationSettings,
    Role,
    Warehouse,
)
from apps.tenancy.services import (
    accept_invitation,
    create_organization,
    invite_member,
    switch_organization,
)

User = get_user_model()


@pytest.mark.django_db
def test_create_organization_provisioning() -> None:
    owner = User.objects.create_user(email="founder@corp.com", password="SecretPassword123!")
    org = create_organization(name="Corp Global", slug="corp-global", owner=owner)

    assert org.pk is not None
    assert str(org) == "Corp Global"

    # Default roles created
    roles = Role.all_tenants.filter(organization=org)
    role_names = set(roles.values_list("name", flat=True))
    assert {"Owner", "Admin", "Manager", "Accountant", "Cashier", "HR", "Viewer"}.issubset(role_names)

    # Headquarters branch created
    branch = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert branch is not None
    assert branch.name == "Main Branch"
    assert str(branch) == "Main Branch"

    # Default warehouse created
    wh = Warehouse.all_tenants.filter(organization=org, is_default=True).first()
    assert wh is not None
    assert wh.name == "Main Warehouse"
    assert str(wh) == "Main Warehouse"

    # Settings created
    settings = OrganizationSettings.all_tenants.filter(organization=org).first()
    assert settings is not None
    assert "Settings for Corp Global" in str(settings)

    # Owner membership created
    membership = Membership.all_tenants.filter(organization=org, user=owner).first()
    assert membership is not None
    assert membership.is_owner
    assert membership.status == Membership.STATUS_ACTIVE
    assert "founder@corp.com in Corp Global" in str(membership)


@pytest.mark.django_db
def test_create_organization_duplicate_slug() -> None:
    owner = User.objects.create_user(email="o1@test.com", password="Pass!")
    create_organization(name="First", slug="my-slug", owner=owner)

    with pytest.raises(ConflictError):
        create_organization(name="Second", slug="my-slug", owner=owner)


@pytest.mark.django_db
def test_invite_member_and_accept_flow() -> None:
    owner = User.objects.create_user(email="owner@test.com", password="Pass!")
    org = create_organization(name="Invite Org", slug="invite-org", owner=owner)

    manager_role = Role.all_tenants.filter(organization=org, name="Manager").first()
    assert manager_role is not None

    # 1. Invite a new team member
    mail.outbox.clear()
    invitation = invite_member(
        organization=org,
        email="newbie@test.com",
        role=manager_role,
        actor=owner,
    )
    assert invitation.pk is not None
    assert invitation.is_valid
    assert len(mail.outbox) == 1
    assert "Invite Org" in mail.outbox[0].subject

    # 2. Existing member cannot be re-invited
    with pytest.raises(ConflictError):
        invite_member(
            organization=org,
            email="owner@test.com",
            role=manager_role,
            actor=owner,
        )

    # 3. Accept invitation
    new_user = User.objects.create_user(email="newbie@test.com", password="Pass!")
    membership = accept_invitation(token=invitation.token, user=new_user)

    assert membership.organization_id == org.pk
    assert membership.role == manager_role
    assert membership.status == Membership.STATUS_ACTIVE

    invitation.refresh_from_db()
    assert invitation.status == Invitation.STATUS_ACCEPTED


@pytest.mark.django_db
def test_switch_organization() -> None:
    u = User.objects.create_user(email="multi@test.com", password="Pass!")
    org1 = create_organization(name="Org One", slug="org-one", owner=u)
    org2 = create_organization(name="Org Two", slug="org-two", owner=u)
    other_org = Organization.objects.create(name="Forbidden", slug="forbidden")

    session = {}
    # Switch to Org 1
    res1 = switch_organization(user=u, organization_id=org1.pk, session=session)
    assert res1 == org1
    assert session["active_org_id"] == org1.pk

    # Switch to Org 2
    res2 = switch_organization(user=u, organization_id=org2.pk, session=session)
    assert res2 == org2
    assert session["active_org_id"] == org2.pk

    # Cannot switch to unjoined org
    with pytest.raises(ValidationError):
        switch_organization(user=u, organization_id=other_org.pk, session=session)
