"""Request/task-scoped tenant context. Set by TenantMiddleware and TenantTask; read by TenantManager and RLS.

Core sits at the bottom of the layer contract, so the organization is typed as a plain Django model here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from django.db import connections
from django.db.backends.signals import connection_created
from django.db.models import Model
from django.dispatch import receiver

from apps.core.exceptions import TenantAccessError

logger = logging.getLogger(__name__)

_current_org_id: ContextVar[int | None] = ContextVar("current_org_id", default=None)
_current_org: ContextVar[Model | None] = ContextVar("current_org", default=None)


def set_tenant_session(org_id: int | None, *, using: str = "default") -> None:
    """Set `app.current_org` in PostgreSQL session for RLS enforcement."""
    try:
        conn = connections[using]
    except Exception:
        return

    if conn.vendor != "postgresql":
        return

    # Only apply to open connections to avoid premature connection establishment
    if conn.connection is None:
        return

    try:
        with conn.cursor() as cursor:
            if org_id is not None:
                cursor.execute("SELECT set_config('app.current_org', %s, false);", [str(org_id)])
            else:
                cursor.execute("SELECT set_config('app.current_org', '', false);")
    except Exception:
        logger.debug("Failed to set app.current_org on connection %s", using, exc_info=True)


@receiver(connection_created)
def _on_connection_created(sender: Any, connection: Any, **kwargs: Any) -> None:
    """Ensure newly established PostgreSQL connections immediately have the active tenant set."""
    if connection.vendor != "postgresql":
        return

    org_id = get_current_organization_id()
    try:
        with connection.cursor() as cursor:
            if org_id is not None:
                cursor.execute("SELECT set_config('app.current_org', %s, false);", [str(org_id)])
            else:
                cursor.execute("SELECT set_config('app.current_org', '', false);")
    except Exception:
        logger.debug("Failed to set initial app.current_org on new connection", exc_info=True)


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


def set_current_organization(org: Model | int | None) -> None:
    """Set active organization globally in context variables and database session."""
    target_org: Model | None = None
    target_org_id: int | None = None

    if isinstance(org, int):
        target_org_id = org
    elif org is not None and hasattr(org, "pk"):
        target_org = org
        target_org_id = org.pk

    _current_org.set(target_org)
    _current_org_id.set(target_org_id)
    set_tenant_session(target_org_id)


@contextmanager
def tenant_context(org: Any) -> Iterator[Any]:
    """Activate `org` (Model, int ID, or None) for the block duration."""
    prev_org_id = _current_org_id.get()

    target_org: Model | None = None
    target_org_id: int | None = None

    if isinstance(org, int):
        target_org_id = org
    elif org is not None and hasattr(org, "pk"):
        target_org = org
        target_org_id = org.pk

    token_org = _current_org.set(target_org)
    token_id = _current_org_id.set(target_org_id)
    set_tenant_session(target_org_id)
    try:
        yield org
    finally:
        _current_org.reset(token_org)
        _current_org_id.reset(token_id)
        set_tenant_session(prev_org_id)
