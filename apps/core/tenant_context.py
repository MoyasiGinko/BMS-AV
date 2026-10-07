"""Request/task-scoped tenant context. Set by TenantMiddleware and TenantTask; read by TenantManager and RLS.

Core sits at the bottom of the layer contract, so the organization is typed as a plain Django model here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from django.db.models import Model

from apps.core.exceptions import TenantAccessError

_current_org_id: ContextVar[int | None] = ContextVar("current_org_id", default=None)
_current_org: ContextVar[Model | None] = ContextVar("current_org", default=None)


def get_current_organization_id() -> int | None:
    return _current_org_id.get()


def get_current_organization() -> Model | None:
    return _current_org.get()


def require_current_organization() -> Model:
    """Return active organization model or raise TenantAccessError."""
    org = _current_org.get()
    if org is None:
        raise TenantAccessError("No active organization in current context.")
    return org


def require_current_organization_id() -> int:
    """Return active organization ID or raise TenantAccessError."""
    org_id = _current_org_id.get()
    if org_id is None:
        raise TenantAccessError("No active organization ID in current context.")
    return org_id


def set_current_organization(org: Model | None) -> None:
    _current_org.set(org)
    _current_org_id.set(org.pk if org is not None else None)


@contextmanager
def tenant_context(org: Any) -> Iterator[Any]:
    """Activate `org` for the duration of the block (restores the previous tenant afterwards)."""
    token_org = _current_org.set(org)
    token_id = _current_org_id.set(getattr(org, "pk", None) if org is not None else None)
    try:
        yield org
    finally:
        _current_org.reset(token_org)
        _current_org_id.reset(token_id)
