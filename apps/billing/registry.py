"""Module and Navigation Registry for Business OS.

Allows modules to declare navigation items, permission dependencies,
and subscription plan requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NavItem:
    """Navigation link specification."""

    title: str
    url_name: str
    icon: str = ""
    permission: str = ""
    badge: str = ""


@dataclass(frozen=True)
class ModuleDefinition:
    """System module specification in the product registry."""

    key: str
    name: str
    description: str = ""
    icon: str = "cube"
    sort_order: int = 100
    is_core: bool = False
    nav_items: list[NavItem] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)


class _ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleDefinition] = {}

    def register(
        self,
        key: str,
        *,
        name: str,
        description: str = "",
        icon: str = "cube",
        sort_order: int = 100,
        is_core: bool = False,
        nav_items: list[NavItem] | None = None,
        permissions: list[str] | None = None,
    ) -> ModuleDefinition:
        mod = ModuleDefinition(
            key=key,
            name=name,
            description=description,
            icon=icon,
            sort_order=sort_order,
            is_core=is_core,
            nav_items=nav_items or [],
            permissions=permissions or [],
        )
        self._modules[key] = mod
        return mod

    def get(self, key: str) -> ModuleDefinition | None:
        return self._modules.get(key)

    def all(self) -> list[ModuleDefinition]:
        return sorted(self._modules.values(), key=lambda m: (m.sort_order, m.name))

    def get_navigation(
        self,
        enabled_module_keys: set[str],
        user_granted_permissions: set[str],
    ) -> list[dict[str, Any]]:
        """Filter navigation items by active plan modules and user permissions."""
        nav_tree: list[dict[str, Any]] = []

        for mod in self.all():
            if not mod.is_core and mod.key not in enabled_module_keys:
                continue

            visible_items = []
            for item in mod.nav_items:
                has_perm = (
                    not item.permission
                    or "*" in user_granted_permissions
                    or item.permission in user_granted_permissions
                )
                if has_perm:
                    visible_items.append(
                        {
                            "title": item.title,
                            "url_name": item.url_name,
                            "icon": item.icon,
                            "badge": item.badge,
                        }
                    )

            if visible_items:
                nav_tree.append(
                    {
                        "module_key": mod.key,
                        "module_name": mod.name,
                        "icon": mod.icon,
                        "items": visible_items,
                    }
                )

        return nav_tree


registry = _ModuleRegistry()

# Register core platform modules
registry.register(
    "billing",
    name="Billing & Plans",
    description="Subscription plans, invoices, and payment management",
    icon="credit-card",
    sort_order=10,
    is_core=True,
    nav_items=[
        NavItem("Subscription", "billing:subscription", icon="credit-card", permission="billing.view"),
        NavItem("Plans", "billing:plans", icon="sparkles", permission="billing.view"),
    ],
    permissions=["billing.view", "billing.manage"],
)

registry.register(
    "settings",
    name="Settings",
    description="Organization, team, number sequences, and regional configuration",
    icon="cog-6-tooth",
    sort_order=20,
    is_core=True,
    nav_items=[
        NavItem(
            "Organization",
            "tenancy:organization_settings",
            icon="building-office",
            permission="tenancy.manage",
        ),
        NavItem("Members & Roles", "tenancy:members", icon="users", permission="users.manage"),
        NavItem("Number Sequences", "core:sequences", icon="hashtag", permission="settings.manage"),
    ],
    permissions=["settings.manage", "tenancy.manage", "users.manage"],
)

registry.register(
    "catalog",
    name="Product Catalog",
    description="Products, variants, barcodes, pricing, and units",
    icon="cube",
    sort_order=30,
    nav_items=[
        NavItem("Products", "catalog:product_list", icon="cube", permission="catalog.view"),
        NavItem("Categories", "catalog:category_list", icon="folder", permission="catalog.view"),
        NavItem("Price Lists", "catalog:pricelist_list", icon="tag", permission="catalog.view"),
        NavItem("Units", "catalog:unit_list", icon="scale", permission="catalog.view"),
    ],
    permissions=["catalog.view", "catalog.manage"],
)

registry.register(
    "inventory",
    name="Inventory & Warehouses",
    description="Stock levels, warehouse locations, and stock movements",
    icon="archive-box",
    sort_order=40,
    nav_items=[
        NavItem(
            "Stock Levels", "inventory:stock_level_list", icon="archive-box", permission="inventory.view"
        ),
        NavItem(
            "Movements", "inventory:movement_list", icon="arrows-right-left", permission="inventory.view"
        ),
        NavItem(
            "Adjustments", "inventory:adjustment_list", icon="pencil-square", permission="inventory.adjust"
        ),
        NavItem("Transfers", "inventory:transfer_list", icon="truck", permission="inventory.transfer"),
        NavItem(
            "Cycle Counts",
            "inventory:count_list",
            icon="clipboard-document-check",
            permission="inventory.count",
        ),
    ],
    permissions=[
        "inventory.view",
        "inventory.create",
        "inventory.adjust",
        "inventory.transfer",
        "inventory.count",
        "inventory.manage",
    ],
)

registry.register(
    "customers",
    name="Customers",
    description="Customer accounts, contact directory, and balances",
    icon="user-group",
    sort_order=50,
    nav_items=[
        NavItem(
            "Customer Directory",
            "customers:customer_list",
            icon="user-group",
            permission="customers.view",
        ),
        NavItem("New Customer", "customers:customer_create", icon="user-plus", permission="customers.create"),
    ],
    permissions=[
        "customers.view",
        "customers.create",
        "customers.update",
        "customers.delete",
        "customers.adjust_balance",
        "customers.export",
    ],
)

registry.register(
    "sales",
    name="Sales & Invoicing",
    description="Quotes, orders, invoices, and credit notes",
    icon="document-text",
    sort_order=60,
    permissions=["sales.view", "sales.create", "sales.manage"],
)

registry.register(
    "pos",
    name="Point of Sale (POS)",
    description="Fast counter checkout, registers, cash shifts, and receipts",
    icon="calculator",
    sort_order=70,
    permissions=["pos.access", "pos.manage"],
)

registry.register(
    "purchasing",
    name="Purchasing",
    description="Suppliers, purchase orders, and vendor bills",
    icon="truck",
    sort_order=80,
    permissions=["purchasing.view", "purchasing.manage"],
)

registry.register(
    "accounting",
    name="Accounting & General Ledger",
    description="Double-entry journals, chart of accounts, and financial closing",
    icon="building-library",
    sort_order=90,
    permissions=["accounting.view", "accounting.post", "accounting.manage"],
)

registry.register(
    "crm",
    name="CRM & Pipelines",
    description="Leads, deals, sales pipeline stages, and activities",
    icon="chat-bubble-left-right",
    sort_order=100,
    permissions=["crm.view", "crm.manage"],
)

registry.register(
    "hr",
    name="Human Resources",
    description="Employee profiles, departments, documents, and attendance",
    icon="identification",
    sort_order=110,
    permissions=["hr.view", "hr.manage"],
)

registry.register(
    "payroll",
    name="Payroll",
    description="Salary structures, payroll calculation runs, and payslips",
    icon="banknotes",
    sort_order=120,
    permissions=["payroll.view", "payroll.manage"],
)

registry.register(
    "reports",
    name="Reports & Analytics",
    description="Operational dashboards, financial statements, and data exports",
    icon="chart-bar",
    sort_order=130,
    permissions=["reports.view", "reports.export"],
)

registry.register(
    "automation",
    name="Automation & Workflows",
    description="Trigger-action event rules, webhooks, and alerts",
    icon="bolt",
    sort_order=140,
    permissions=["settings.manage"],
)

registry.register(
    "integrations",
    name="Integrations & API",
    description="API keys, webhooks, external connectors, and import/export",
    icon="arrow-path",
    sort_order=150,
    permissions=["settings.manage"],
)

registry.register(
    "ai",
    name="AI Assistant",
    description="Copilot actions, automated document extraction, and insights",
    icon="sparkles",
    sort_order=160,
    permissions=["settings.manage"],
)
