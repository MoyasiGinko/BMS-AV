"""Billing role permissions registration."""

from __future__ import annotations

from apps.core.permissions import register_permission


def register_billing_permissions() -> None:
    """Register billing permissions in core catalog."""
    register_permission(
        "billing.view",
        description="View subscription, plan details, invoices, and usage counters",
        module="billing",
    )
    register_permission(
        "billing.manage",
        description="Change plans, manage payment methods, and cancel subscriptions",
        module="billing",
    )
