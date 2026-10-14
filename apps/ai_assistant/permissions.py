"""Permission constants and checkers for the AI Assistant module."""

from __future__ import annotations

from typing import Any

from apps.tenancy.models import Membership

PERMISSION_CHAT = "ai.chat"
PERMISSION_MANAGE = "ai.manage"
PERMISSION_ACTIONS = "ai.actions"


def user_has_ai_permission(user: Any, organization_id: int, permission: str) -> bool:
    """Check if user has a specific AI permission within the tenant organization."""
    if not user or not user.is_authenticated:
        return False

    if getattr(user, "is_superuser", False):
        return True

    membership = (
        Membership.all_tenants.filter(
            organization_id=organization_id,
            user=user,
            status=Membership.STATUS_ACTIVE,
        )
        .select_related("role")
        .first()
    )

    if not membership:
        return False

    if membership.is_owner:
        return True

    perms: list[str] = getattr(membership.role, "permissions", []) or []
    prefix = permission.split(".", maxsplit=1)[0] + ".*"
    return "*" in perms or permission in perms or prefix in perms
