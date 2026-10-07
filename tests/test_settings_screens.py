"""Tests for tenant workspace settings screens, navigation, and CRUD workflows."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.billing.models import Plan
from apps.billing.services import create_subscription, seed_default_plans
from apps.tenancy import selectors
from apps.tenancy.models import (
    Branch,
    Currency,
    Department,
    Membership,
    Organization,
    Role,
    TaxCode,
    Warehouse,
)
from apps.tenancy.services import create_organization


@pytest.fixture(autouse=True)
def clean_env() -> None:
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def plans(db: None) -> dict[str, Plan]:
    return seed_default_plans()


@pytest.fixture
def owner_a(db: None) -> User:
    return User.objects.create_user(email="settings_owner_a@example.com", password="Password123!")


@pytest.fixture
def member_a(db: None) -> User:
    return User.objects.create_user(email="settings_member_a@example.com", password="Password123!")


@pytest.fixture
def owner_b(db: None) -> User:
    return User.objects.create_user(email="settings_owner_b@example.com", password="Password123!")


@pytest.fixture
def org_a(db: None, owner_a: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Alpha Corp", slug="alpha-corp", owner=owner_a)
    create_subscription(organization=org, plan=plans["starter"], actor=owner_a, trial_days=0)
    return org


@pytest.fixture
def org_b(db: None, owner_b: User, plans: dict[str, Plan]) -> Organization:
    org = create_organization(name="Beta Corp", slug="beta-corp", owner=owner_b)
    create_subscription(organization=org, plan=plans["starter"], actor=owner_b, trial_days=0)
    return org


def _make_client(user: User, org: Organization) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["active_org_id"] = org.id
    session.save()
    return client


# ---------------------------------------------------------------------------
# Navigation & Unauthenticated Access
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_settings_requires_login() -> None:
    client = Client()
    resp = client.get("/settings/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp.url


@pytest.mark.django_db
def test_settings_index_redirects_to_general(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)
    resp = client.get("/settings/")
    assert resp.status_code == 302
    assert resp.url == "/settings/general/"


@pytest.mark.django_db
def test_all_settings_screens_load_200(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)
    urls = [
        "/settings/general/",
        "/settings/branches/",
        "/settings/warehouses/",
        "/settings/departments/",
        "/settings/users/",
        "/settings/roles/",
        "/settings/numbering/",
        "/settings/tax-codes/",
        "/settings/currencies/",
        "/settings/notifications/",
    ]
    for url in urls:
        resp = client.get(url)
        assert resp.status_code == 200, f"Failed for {url}"


# ---------------------------------------------------------------------------
# 1. General Settings
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_general_settings(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    payload = {
        "name": "Alpha Global Holdings",
        "base_currency": "GBP",
        "country": "GB",
        "timezone": "Europe/London",
        "fiscal_year_start": 4,
        "date_format": "DD/MM/YYYY",
        "costing_method": "fifo",
        "allow_negative_stock": "on",
        "tax_inclusive_pricing": "on",
    }
    resp = client.post("/settings/general/", payload)
    assert resp.status_code == 302
    assert resp.url == "/settings/general/"

    org_a.refresh_from_db()
    assert org_a.name == "Alpha Global Holdings"
    assert org_a.base_currency == "GBP"
    assert org_a.country == "GB"
    assert org_a.timezone == "Europe/London"
    assert org_a.fiscal_year_start == 4
    assert org_a.date_format == "DD/MM/YYYY"

    settings_obj = selectors.get_organization_settings(organization_id=org_a.pk)
    assert settings_obj.costing_method == "fifo"
    assert settings_obj.allow_negative_stock is True
    assert settings_obj.tax_inclusive_pricing is True


# ---------------------------------------------------------------------------
# 2. Branches
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_branch_crud_and_safety(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    # 1. Create a new branch
    resp = client.post(
        "/settings/branches/",
        {
            "name": "North Logistics Hub",
            "code": "NLH",
            "address": "42 Harbor Way",
            "phone": "+1-555-0199",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    branch = Branch.all_tenants.get(organization=org_a, code="NLH")
    assert branch.name == "North Logistics Hub"
    assert branch.is_headquarters is False

    # 2. Update branch
    resp = client.post(
        "/settings/branches/",
        {
            "branch_id": str(branch.pk),
            "name": "North Logistics Center",
            "code": "NLC",
            "address": "42 Harbor Way Suite B",
            "phone": "+1-555-0199",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    branch.refresh_from_db()
    assert branch.name == "North Logistics Center"
    assert branch.code == "NLC"

    # 3. Delete branch
    resp = client.post(
        "/settings/branches/",
        {
            "action": "delete",
            "branch_id": str(branch.pk),
        },
    )
    assert resp.status_code == 302
    assert not Branch.all_tenants.filter(pk=branch.pk).exists()

    # 4. Headquarters deletion rejected
    hq_branch = Branch.all_tenants.get(organization=org_a, is_headquarters=True)
    resp = client.post(
        "/settings/branches/",
        {
            "action": "delete",
            "branch_id": str(hq_branch.pk),
        },
    )
    assert resp.status_code == 302
    assert Branch.all_tenants.filter(pk=hq_branch.pk).exists()


# ---------------------------------------------------------------------------
# 3. Warehouses
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_warehouse_crud_and_safety(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)
    branch = selectors.list_organization_branches(organization_id=org_a.pk)[0]

    # 1. Create warehouse
    resp = client.post(
        "/settings/warehouses/",
        {
            "name": "Regional Annex",
            "code": "ANNEX-1",
            "branch_id": str(branch.pk),
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    wh = Warehouse.all_tenants.get(organization=org_a, code="ANNEX-1")
    assert wh.name == "Regional Annex"
    assert wh.is_default is False

    # 2. Update warehouse
    resp = client.post(
        "/settings/warehouses/",
        {
            "warehouse_id": str(wh.pk),
            "name": "Regional Annex West",
            "code": "ANNEX-W",
            "branch_id": str(branch.pk),
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    wh.refresh_from_db()
    assert wh.name == "Regional Annex West"
    assert wh.code == "ANNEX-W"

    # 3. Delete warehouse
    resp = client.post(
        "/settings/warehouses/",
        {
            "action": "delete",
            "warehouse_id": str(wh.pk),
        },
    )
    assert resp.status_code == 302
    assert not Warehouse.all_tenants.filter(pk=wh.pk).exists()

    # 4. Default warehouse deletion rejected
    default_wh = Warehouse.all_tenants.get(organization=org_a, is_default=True)
    resp = client.post(
        "/settings/warehouses/",
        {
            "action": "delete",
            "warehouse_id": str(default_wh.pk),
        },
    )
    assert resp.status_code == 302
    assert Warehouse.all_tenants.filter(pk=default_wh.pk).exists()


# ---------------------------------------------------------------------------
# 4. Departments
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_department_crud_and_hierarchy(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    # 1. Create top department
    resp = client.post(
        "/settings/departments/",
        {
            "name": "Engineering",
            "code": "ENG",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    eng_dept = Department.all_tenants.get(organization=org_a, code="ENG")

    # 2. Create sub-department with parent
    resp = client.post(
        "/settings/departments/",
        {
            "name": "Backend Team",
            "code": "ENG-BE",
            "parent_id": str(eng_dept.pk),
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    be_dept = Department.all_tenants.get(organization=org_a, code="ENG-BE")
    assert be_dept.parent_id == eng_dept.pk

    # 3. Update department
    resp = client.post(
        "/settings/departments/",
        {
            "department_id": str(be_dept.pk),
            "name": "Platform Engineering",
            "code": "ENG-PLT",
            "parent_id": str(eng_dept.pk),
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    be_dept.refresh_from_db()
    assert be_dept.name == "Platform Engineering"
    assert be_dept.code == "ENG-PLT"

    # 4. Delete sub-department
    resp = client.post(
        "/settings/departments/",
        {
            "action": "delete",
            "department_id": str(be_dept.pk),
        },
    )
    assert resp.status_code == 302
    assert not Department.all_tenants.filter(pk=be_dept.pk).exists()


# ---------------------------------------------------------------------------
# 5. Team Members & Invitations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_invitation_and_membership_management(
    org_a: Organization,
    owner_a: User,
    member_a: User,
) -> None:
    client = _make_client(owner_a, org_a)
    member_role = Role.all_tenants.get(organization=org_a, name="Viewer")
    manager_role = Role.all_tenants.get(organization=org_a, name="Manager")

    # 1. Invite new user
    resp = client.post(
        "/settings/users/",
        {
            "action": "invite",
            "email": "invitee@example.com",
            "role_id": str(member_role.pk),
        },
    )
    assert resp.status_code == 302
    invites = selectors.list_organization_invitations(organization_id=org_a.pk)
    assert any(i.email == "invitee@example.com" for i in invites)
    invite = next(i for i in invites if i.email == "invitee@example.com")

    # 2. Revoke invitation
    resp = client.post(
        "/settings/users/",
        {
            "action": "revoke_invite",
            "token": invite.token,
        },
    )
    assert resp.status_code == 302
    assert not selectors.list_organization_invitations(organization_id=org_a.pk).filter(pk=invite.pk).exists()

    # 3. Add a member directly and test role/status update + removal
    membership = Membership.objects.create(
        organization=org_a,
        user=member_a,
        role=member_role,
        status=Membership.STATUS_ACTIVE,
    )

    resp = client.post(
        "/settings/users/",
        {
            "action": "update_role",
            "membership_id": str(membership.pk),
            "role_id": str(manager_role.pk),
            "status": Membership.STATUS_SUSPENDED,
        },
    )
    assert resp.status_code == 302
    membership.refresh_from_db()
    assert membership.role_id == manager_role.pk
    assert membership.status == Membership.STATUS_SUSPENDED

    # 4. Remove member
    resp = client.post(
        "/settings/users/",
        {
            "action": "remove_member",
            "membership_id": str(membership.pk),
        },
    )
    assert resp.status_code == 302
    assert not Membership.objects.filter(pk=membership.pk).exists()


# ---------------------------------------------------------------------------
# 6. Roles & Permissions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_custom_role_crud_and_safety(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    # 1. Create custom role
    resp = client.post(
        "/settings/roles/",
        {
            "name": "Audit Auditor",
            "description": "Read-only access to reports and financial ledgers",
            "permissions": ["settings.view", "users.view"],
        },
    )
    assert resp.status_code == 302
    role = Role.all_tenants.get(organization=org_a, name="Audit Auditor")
    assert role.is_system is False
    assert "settings.view" in role.permissions
    assert "users.view" in role.permissions

    # 2. Update custom role
    resp = client.post(
        "/settings/roles/",
        {
            "role_id": str(role.pk),
            "name": "Senior Auditor",
            "description": "Expanded audit visibility",
            "permissions": ["settings.view", "users.view", "roles.view"],
        },
    )
    assert resp.status_code == 302
    role.refresh_from_db()
    assert role.name == "Senior Auditor"
    assert "roles.view" in role.permissions

    # 3. Delete custom role
    resp = client.post(
        "/settings/roles/",
        {
            "action": "delete",
            "role_id": str(role.pk),
        },
    )
    assert resp.status_code == 302
    assert not Role.all_tenants.filter(pk=role.pk).exists()

    # 4. System role deletion rejected
    owner_role = Role.all_tenants.get(organization=org_a, name="Owner")
    resp = client.post(
        "/settings/roles/",
        {
            "action": "delete",
            "role_id": str(owner_role.pk),
        },
    )
    assert resp.status_code == 302
    assert Role.all_tenants.filter(pk=owner_role.pk).exists()


# ---------------------------------------------------------------------------
# 7. Document Numbering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_number_sequence(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)
    seq = selectors.list_organization_number_sequences(organization_id=org_a.pk)[0]

    resp = client.post(
        "/settings/numbering/",
        {
            "sequence_id": str(seq.pk),
            "prefix": "DOC-",
            "suffix": "-2026",
            "next_number": "105",
            "padding": "6",
            "reset_frequency": "yearly",
        },
    )
    assert resp.status_code == 302
    seq.refresh_from_db()
    assert seq.prefix == "DOC-"
    assert seq.suffix == "-2026"
    assert seq.next_number == 105
    assert seq.padding == 6
    assert seq.reset_frequency == "yearly"


# ---------------------------------------------------------------------------
# 8. Tax Codes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tax_code_crud(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    # 1. Create tax code
    resp = client.post(
        "/settings/tax-codes/",
        {
            "code": "VAT-15",
            "name": "Standard VAT 15%",
            "rate": "15.0000",
            "is_inclusive": "on",
            "is_default": "on",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    tax = TaxCode.all_tenants.get(organization=org_a, code="VAT-15")
    assert tax.rate == Decimal("15.0000")
    assert tax.is_inclusive is True
    assert tax.is_default is True

    # 2. Update tax code
    resp = client.post(
        "/settings/tax-codes/",
        {
            "tax_code_id": str(tax.pk),
            "code": "VAT-15",
            "name": "Standard VAT 15% Revised",
            "rate": "15.5000",
            "is_inclusive": "on",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    tax.refresh_from_db()
    assert tax.name == "Standard VAT 15% Revised"
    assert tax.rate == Decimal("15.5000")

    # 3. Delete tax code
    resp = client.post(
        "/settings/tax-codes/",
        {
            "action": "delete",
            "tax_code_id": str(tax.pk),
        },
    )
    assert resp.status_code == 302
    assert not TaxCode.all_tenants.filter(pk=tax.pk).exists()


# ---------------------------------------------------------------------------
# 9. Currencies
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_currency_crud_and_safety(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    # 1. Create foreign currency
    resp = client.post(
        "/settings/currencies/",
        {
            "code": "EUR",
            "name": "Euro",
            "symbol": "€",
            "exchange_rate": "1.085000",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    eur = Currency.all_tenants.get(organization=org_a, code="EUR")
    assert eur.exchange_rate == Decimal("1.085000")
    assert eur.is_base is False

    # 2. Update currency
    resp = client.post(
        "/settings/currencies/",
        {
            "currency_id": str(eur.pk),
            "code": "EUR",
            "name": "Eurozone Common Currency",
            "symbol": "€",
            "exchange_rate": "1.090000",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    eur.refresh_from_db()
    assert eur.name == "Eurozone Common Currency"
    assert eur.exchange_rate == Decimal("1.090000")

    # 3. Delete foreign currency
    resp = client.post(
        "/settings/currencies/",
        {
            "action": "delete",
            "currency_id": str(eur.pk),
        },
    )
    assert resp.status_code == 302
    assert not Currency.all_tenants.filter(pk=eur.pk).exists()

    # 4. Base currency deletion rejected
    base_curr = Currency.all_tenants.get(organization=org_a, is_base=True)
    resp = client.post(
        "/settings/currencies/",
        {
            "action": "delete",
            "currency_id": str(base_curr.pk),
        },
    )
    assert resp.status_code == 302
    assert Currency.all_tenants.filter(pk=base_curr.pk).exists()


# ---------------------------------------------------------------------------
# 10. Notification Preferences
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_notification_preferences_update(org_a: Organization, owner_a: User) -> None:
    client = _make_client(owner_a, org_a)

    resp = client.post(
        "/settings/notifications/",
        {
            "billing_email": "on",
            "billing_in_app": "on",
            "inventory_email": "on",
            # inventory_in_app omitted (unchecked)
            # sales_email omitted
            "sales_in_app": "on",
            "security_email": "on",
            "security_in_app": "on",
        },
    )
    assert resp.status_code == 302
    assert resp.url == "/settings/notifications/"

    prefs = selectors.list_organization_notification_preferences(organization_id=org_a.pk)
    pref_dict = {(p.category, p.channel): p.is_enabled for p in prefs}

    assert pref_dict[("billing", "email")] is True
    assert pref_dict[("inventory", "email")] is True
    assert pref_dict[("inventory", "in_app")] is False
    assert pref_dict[("sales", "email")] is False
    assert pref_dict[("sales", "in_app")] is True
    assert pref_dict[("security", "email")] is True


# ---------------------------------------------------------------------------
# 11. Cross-Tenant Isolation & Permissions Enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_settings_permission_enforcement(
    org_a: Organization,
    member_a: User,
) -> None:
    # member_a has 'Viewer' role without 'settings.view' or 'settings.manage'
    member_role = Role.all_tenants.get(organization=org_a, name="Viewer")
    Membership.objects.create(
        organization=org_a,
        user=member_a,
        role=member_role,
        status=Membership.STATUS_ACTIVE,
    )

    client = _make_client(member_a, org_a)

    # Viewing settings should raise PermissionDenied (403)
    resp = client.get("/settings/general/")
    assert resp.status_code == 403

    resp = client.post(
        "/settings/general/",
        {
            "name": "Hacked Name",
            "base_currency": "USD",
            "country": "US",
            "timezone": "UTC",
            "fiscal_year_start": 1,
            "date_format": "YYYY-MM-DD",
            "costing_method": "fifo",
        },
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_cross_tenant_isolation_on_settings_mutations(
    org_a: Organization,
    owner_a: User,
    org_b: Organization,
    owner_b: User,
) -> None:
    # Org B creates a branch and a tax code
    branch_b = Branch.all_tenants.filter(organization=org_b).first()
    tax_b = TaxCode.all_tenants.create(
        organization=org_b,
        code="TAX-B",
        name="Org B Tax",
        rate=Decimal("10.00"),
    )

    # Client A logged in under Org A tries to delete Org B's records
    client_a = _make_client(owner_a, org_a)

    # 1. Attempt to delete Org B's branch
    client_a.post(
        "/settings/branches/",
        {
            "action": "delete",
            "branch_id": str(branch_b.pk),
        },
    )
    assert Branch.all_tenants.filter(pk=branch_b.pk).exists()

    # 2. Attempt to delete Org B's tax code
    client_a.post(
        "/settings/tax-codes/",
        {
            "action": "delete",
            "tax_code_id": str(tax_b.pk),
        },
    )
    assert TaxCode.all_tenants.filter(pk=tax_b.pk).exists()
