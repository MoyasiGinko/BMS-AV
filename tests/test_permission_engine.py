"""Tests for the 3-layer permission engine: feature entitlement, role permissions, and object scope."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
from django.views.generic import View

from apps.accounts.models import User
from apps.core.permissions import (
    FeatureRequiredMixin,
    check_object_scope,
    clear_feature_overrides,
    feature_required,
    has_feature_entitlement,
    has_permission,
    permission_required,
    register_entitlement_checker,
    scope_queryset,
    set_feature_override,
)
from apps.core.tenant_context import tenant_context
from apps.tenancy.models import Branch, Membership, MembershipBranch, Organization, Role
from apps.tenancy.services import create_organization


@pytest.fixture
def org_and_users(db: None) -> dict[str, object]:
    owner = User.objects.create_user(email="perm_owner@example.com", password="Password123!")
    cashier = User.objects.create_user(email="perm_cashier@example.com", password="Password123!")
    viewer = User.objects.create_user(email="perm_viewer@example.com", password="Password123!")

    org = create_organization(name="Permissions Inc", slug="perms-inc", owner=owner)

    role_cashier = Role.all_tenants.filter(organization=org, name="Cashier").first()
    assert role_cashier is not None
    role_viewer = Role.all_tenants.filter(organization=org, name="Viewer").first()
    assert role_viewer is not None

    mem_cashier = Membership.all_tenants.create(
        organization=org,
        user=cashier,
        role=role_cashier,
        status=Membership.STATUS_ACTIVE,
    )
    mem_viewer = Membership.all_tenants.create(
        organization=org,
        user=viewer,
        role=role_viewer,
        status=Membership.STATUS_ACTIVE,
    )

    branch_hq = Branch.all_tenants.filter(organization=org, is_headquarters=True).first()
    assert branch_hq is not None

    branch_second = Branch.all_tenants.create(
        organization=org,
        name="Second Branch",
        code="SEC",
    )

    # Restrict cashier to branch_second only
    MembershipBranch.all_tenants.create(
        organization=org,
        membership=mem_cashier,
        branch=branch_second,
    )

    return {
        "org": org,
        "owner": owner,
        "cashier": cashier,
        "viewer": viewer,
        "branch_hq": branch_hq,
        "branch_second": branch_second,
        "mem_cashier": mem_cashier,
        "mem_viewer": mem_viewer,
    }


# ===========================================================================
# Layer 1: Feature Entitlement Tests
# ===========================================================================


@pytest.mark.django_db
def test_layer1_feature_entitlement(org_and_users: dict[str, object], rf: RequestFactory) -> None:
    org = org_and_users["org"]
    assert isinstance(org, Organization)
    owner = org_and_users["owner"]

    # 1. Allowed feature
    assert has_feature_entitlement(org, "catalog.view") is True

    @feature_required("catalog.view")
    def allowed_view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("Allowed")

    req = rf.get("/")
    req.user = owner
    req.organization = org
    resp = allowed_view(req)
    assert resp.status_code == 200
    assert resp.content == b"Allowed"

    # 2. Denied feature via override
    clear_feature_overrides()
    set_feature_override(org.id, "sales.enterprise", False)

    assert has_feature_entitlement(org, "sales.enterprise") is False

    @feature_required("sales.enterprise")
    def denied_view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("Enterprise")

    with pytest.raises(PermissionDenied):
        denied_view(req)

    clear_feature_overrides()


@pytest.mark.django_db
def test_layer1_feature_entitlement_mixin(org_and_users: dict[str, object], rf: RequestFactory) -> None:
    org = org_and_users["org"]
    assert isinstance(org, Organization)
    owner = org_and_users["owner"]

    class SampleCBV(FeatureRequiredMixin, View):
        required_feature = "pos.advanced"

        def get(self, request: HttpRequest) -> HttpResponse:
            return HttpResponse("CBV OK")

    view = SampleCBV.as_view()
    req = rf.get("/")
    req.user = owner
    req.organization = org

    # Initially allowed
    resp = view(req)
    assert resp.status_code == 200

    # Denied by custom checker
    register_entitlement_checker(lambda o, f: False if f == "pos.advanced" else None)
    with pytest.raises(PermissionDenied):
        view(req)


# ===========================================================================
# Layer 2: Role Permission Tests
# ===========================================================================


@pytest.mark.django_db
def test_layer2_role_permissions(org_and_users: dict[str, object], rf: RequestFactory) -> None:
    org = org_and_users["org"]
    owner = org_and_users["owner"]
    cashier = org_and_users["cashier"]
    viewer = org_and_users["viewer"]

    # 1. Owner has global access (*)
    assert has_permission(owner, "accounting.post", organization=org) is True
    assert has_permission(owner, "any.arbitrary.action", organization=org) is True

    # 2. Cashier has pos.* and sales.create, but NOT accounting.post
    assert has_permission(cashier, "pos.checkout", organization=org) is True
    assert has_permission(cashier, "sales.create", organization=org) is True
    assert has_permission(cashier, "accounting.post", organization=org) is False

    # 3. Viewer has catalog.view, but NOT sales.create
    assert has_permission(viewer, "catalog.view", organization=org) is True
    assert has_permission(viewer, "sales.create", organization=org) is False

    # Test decorator behavior
    @permission_required("sales.create")
    def create_sale_view(request: HttpRequest) -> HttpResponse:
        return HttpResponse("Sale Created")

    req_cashier = rf.post("/sales/create/")
    req_cashier.user = cashier
    req_cashier.organization = org
    assert create_sale_view(req_cashier).status_code == 200

    req_viewer = rf.post("/sales/create/")
    req_viewer.user = viewer
    req_viewer.organization = org
    with pytest.raises(PermissionDenied):
        create_sale_view(req_viewer)


# ===========================================================================
# Layer 3: Object Scope (Branch) Tests
# ===========================================================================


@pytest.mark.django_db
def test_layer3_object_scope(org_and_users: dict[str, object]) -> None:
    org = org_and_users["org"]
    owner = org_and_users["owner"]
    cashier = org_and_users["cashier"]
    branch_hq = org_and_users["branch_hq"]
    branch_second = org_and_users["branch_second"]

    # 1. Owner has unrestricted branch scope
    all_branches = scope_queryset(Branch.all_tenants.filter(organization=org), owner, organization=org)
    assert all_branches.count() == 2
    assert check_object_scope(owner, branch_hq, organization=org) is True
    assert check_object_scope(owner, branch_second, organization=org) is True

    # 2. Cashier is restricted to branch_second only
    cashier_branches = scope_queryset(Branch.all_tenants.filter(organization=org), cashier, organization=org)
    assert cashier_branches.count() == 1
    assert cashier_branches.first() == branch_second

    assert check_object_scope(cashier, branch_second, organization=org) is True
    assert check_object_scope(cashier, branch_hq, organization=org) is False


# ===========================================================================
# Full 3-Layer Integration Web Test
# ===========================================================================


@pytest.mark.django_db
def test_full_three_layer_web_enforcement(org_and_users: dict[str, object], rf: RequestFactory) -> None:
    """End-to-end web test asserting all three permission layers are enforced."""
    org = org_and_users["org"]
    cashier = org_and_users["cashier"]
    viewer = org_and_users["viewer"]
    branch_hq = org_and_users["branch_hq"]
    branch_second = org_and_users["branch_second"]

    @feature_required("pos.terminal")
    @permission_required("pos.access")
    def pos_checkout_view(request: HttpRequest, branch_id: int) -> HttpResponse:
        # Layer 3 check
        branch = Branch.all_tenants.filter(organization=request.organization, id=branch_id).first()
        if not branch or not check_object_scope(request.user, branch, organization=request.organization):
            raise PermissionDenied("Branch scope denied")
        return HttpResponse(f"POS checkout open on {branch.name}")

    with tenant_context(org):
        # Case A: Fails Layer 1 (Plan does not entitle pos.terminal)
        set_feature_override(org.id, "pos.terminal", False)

        req = rf.get("/pos/")
        req.user = cashier
        req.organization = org
        with pytest.raises(PermissionDenied) as exc_info:
            pos_checkout_view(req, branch_id=branch_second.id)
        assert "current plan does not include" in str(exc_info.value)

        # Re-enable feature
        clear_feature_overrides()

        # Case B: Fails Layer 2 (Viewer role lacks pos.access permission)
        req.user = viewer
        with pytest.raises(PermissionDenied) as exc_info:
            pos_checkout_view(req, branch_id=branch_second.id)
        assert "not have the required permission" in str(exc_info.value)

        # Case C: Fails Layer 3 (Cashier has feature & permission, but lacks access to Headquarters branch)
        req.user = cashier
        with pytest.raises(PermissionDenied) as exc_info:
            pos_checkout_view(req, branch_id=branch_hq.id)
        assert "Branch scope denied" in str(exc_info.value)

        # Case D: Passes all 3 layers!
        resp = pos_checkout_view(req, branch_id=branch_second.id)
        assert resp.status_code == 200
        assert resp.content == b"POS checkout open on Second Branch"
