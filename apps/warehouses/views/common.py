"""Common helpers and permissions for warehouse views."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest
from django.utils.translation import gettext as _

from apps.core.exceptions import ValidationError as DomainValidationError
from apps.core.permissions import has_permission
from apps.core.tenant_context import get_current_organization
from apps.tenancy.models import Organization

ValidationError = (DjangoValidationError, DomainValidationError)


def get_org(request: HttpRequest) -> Organization:
    org: Organization | None = (
        getattr(request, "organization", None)
        or getattr(request, "tenant", None)
        or get_current_organization()
    )
    if not org:
        raise PermissionDenied(_("No active organization found."))
    return org


def can_view(user: Any, org: Organization) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return (
        has_permission(user, "warehouses.view", organization=org)
        or has_permission(user, "inventory.view", organization=org)
        or has_permission(user, "settings.view", organization=org)
    )


def can_manage(user: Any, org: Organization) -> bool:
    if getattr(user, "is_superuser", False):
        return True
    return (
        has_permission(user, "warehouses.manage", organization=org)
        or has_permission(user, "inventory.manage", organization=org)
        or has_permission(user, "tenancy.manage", organization=org)
    )
