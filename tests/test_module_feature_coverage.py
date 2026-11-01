"""Tests for module & feature registry, dependency cascading, resolution precedence, and URL coverage.

Enforces AGENTS.md Section 6:
- Every URL pattern maps to a module or feature key (or core infrastructure).
- Modules declare `depends_on`.
- Resolution order: Core -> Plan -> Tenant DB Override -> Dependency cascading.
"""

from __future__ import annotations

import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from apps.billing.models import Module, Plan, PlanModule, Subscription
from apps.billing.registry import registry
from apps.billing.services import (
    check_organization_feature_entitlement,
    get_organization_enabled_modules,
    set_organization_feature_override,
)
from apps.tenancy.models import Organization

CORE_ALLOWLISTED_PREFIXES = {
    "",
    "admin",
    "accounts",
    "oauth",
    "healthz",
    "readyz",
    "manifest",
    "service-worker",
    "offline",
    "dashboard",
    "settings/theme",
    "theme-manager",
    "tenancy",
    "settings",
    "billing",
    "notifications",
    "help",
    "backoffice",
    "api",
}


@pytest.mark.django_db
class TestModuleFeatureRegistry:
    def test_module_dependency_declarations(self) -> None:
        """Verify registered modules declare their required domain dependencies."""
        pos = registry.get("pos")
        assert pos is not None
        assert set(pos.depends_on) == {"catalog", "inventory", "sales"}

        sales = registry.get("sales")
        assert sales is not None
        assert set(sales.depends_on) == {"catalog", "customers"}

        inventory = registry.get("inventory")
        assert inventory is not None
        assert set(inventory.depends_on) == {"catalog"}

        purchasing = registry.get("purchasing")
        assert purchasing is not None
        assert set(purchasing.depends_on) == {"catalog", "inventory"}

        crm = registry.get("crm")
        assert crm is not None
        assert set(crm.depends_on) == {"customers"}

        payroll = registry.get("payroll")
        assert payroll is not None
        assert set(payroll.depends_on) == {"hr", "accounting"}

    def test_dependency_cascading_logic(self) -> None:
        """Disabling a prerequisite module cascades to disable dependent modules."""
        # POS requires catalog, inventory, sales (which requires catalog, customers)
        full_suite = {"catalog", "customers", "inventory", "sales", "pos"}
        valid = registry.validate_dependencies(full_suite)
        assert valid == full_suite

        # If catalog is missing, inventory, sales, and pos must all be stripped
        without_catalog = {"customers", "inventory", "sales", "pos"}
        validated = registry.validate_dependencies(without_catalog)
        assert "catalog" not in validated
        assert "inventory" not in validated
        assert "sales" not in validated
        assert "pos" not in validated
        assert "customers" in validated

    def test_resolution_order_core_always_enabled(self) -> None:
        """Core modules (billing, settings) are always enabled regardless of plan or overrides."""
        org = Organization.objects.create(name="Test Org", slug="test-org-core")

        # Even with an explicit override trying to disable billing, core remains enabled
        set_organization_feature_override(organization=org, feature_code="billing", is_enabled=False)

        assert check_organization_feature_entitlement(org, "billing") is True
        assert check_organization_feature_entitlement(org, "settings") is True

    def test_resolution_order_plan_and_override_precedence(self) -> None:
        """Plan grants modules, and explicit DB override can disable or grant additional modules."""
        org = Organization.objects.create(name="Retail Co", slug="retail-co")
        plan = Plan.objects.create(name="Starter", slug="starter", price_monthly=0)
        Subscription.objects.create(organization=org, plan=plan, status=Subscription.STATUS_ACTIVE)

        # Plan only includes catalog and customers
        cat_mod, _ = Module.objects.get_or_create(key="catalog", defaults={"name": "Catalog"})
        cust_mod, _ = Module.objects.get_or_create(key="customers", defaults={"name": "Customers"})
        PlanModule.objects.create(plan=plan, module=cat_mod, included=True)
        PlanModule.objects.create(plan=plan, module=cust_mod, included=True)

        # Catalog and customers enabled under plan
        assert check_organization_feature_entitlement(org, "catalog") is True
        assert check_organization_feature_entitlement(org, "customers") is True
        # POS is not in plan -> False
        assert check_organization_feature_entitlement(org, "pos") is False

        # Explicit tenant override grants inventory & sales
        Module.objects.get_or_create(key="inventory", defaults={"name": "Inventory"})
        Module.objects.get_or_create(key="sales", defaults={"name": "Sales"})
        set_organization_feature_override(organization=org, feature_code="inventory", is_enabled=True)
        set_organization_feature_override(organization=org, feature_code="sales", is_enabled=True)

        enabled = get_organization_enabled_modules(org)
        assert "inventory" in enabled
        assert "sales" in enabled

        # Now override POS to True -> with dependencies met, POS should now be True
        set_organization_feature_override(organization=org, feature_code="pos", is_enabled=True)
        assert check_organization_feature_entitlement(org, "pos") is True

        # If tenant override disables catalog, pos and sales cascade to False!
        set_organization_feature_override(organization=org, feature_code="catalog", is_enabled=False)
        assert check_organization_feature_entitlement(org, "catalog") is False
        assert check_organization_feature_entitlement(org, "pos") is False
        assert check_organization_feature_entitlement(org, "sales") is False

    def test_all_url_patterns_mapped_to_module_or_core(self) -> None:
        """Every top-level URL pattern maps to a registered module key or allowlisted core route."""
        resolver = get_resolver()
        registered_keys = {m.key for m in registry.all()}

        unmapped: list[str] = []
        for pattern in resolver.url_patterns:
            route_str = str(pattern.pattern)
            clean_route = route_str.strip("^/").split("/")[0]

            if isinstance(pattern, URLResolver):
                ns = pattern.namespace
                # If namespace matches a registered module, it is valid
                if ns and ns in registered_keys:
                    continue
                # If path or namespace is an allowlisted core route
                if clean_route in CORE_ALLOWLISTED_PREFIXES or any(
                    clean_route.startswith(p) for p in CORE_ALLOWLISTED_PREFIXES if p
                ):
                    continue
                if ns and any(ns.startswith(p) for p in CORE_ALLOWLISTED_PREFIXES if p):
                    continue
                unmapped.append(f"Resolver(route='{route_str}', namespace='{ns}')")
            elif isinstance(pattern, URLPattern):
                name = pattern.name or ""
                if clean_route in CORE_ALLOWLISTED_PREFIXES or any(
                    clean_route.startswith(p) for p in CORE_ALLOWLISTED_PREFIXES if p
                ):
                    continue
                if clean_route in registered_keys:
                    continue
                unmapped.append(f"Pattern(route='{route_str}', name='{name}')")

        assert not unmapped, f"Found URL routes without module or feature key mapping: {unmapped}"
