"""Platform lifecycle hooks registry.

Allows decoupled modules across all architectural layers to register
hooks for tenant provisioning, tenant teardown, and cross-cutting lifecycle events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_PROVISIONING_HOOKS: list[Callable[[Any], None]] = []


def register_provisioning_hook(hook_fn: Callable[[Any], None]) -> None:
    """Register a callback executed inside the organization provisioning transaction."""
    if hook_fn not in _PROVISIONING_HOOKS:
        _PROVISIONING_HOOKS.append(hook_fn)


def clear_provisioning_hooks() -> None:
    """Clear registered provisioning hooks (used in clean test teardowns)."""
    _PROVISIONING_HOOKS.clear()


def run_provisioning_hooks(ctx: Any) -> None:
    """Run all registered provisioning callbacks in registration order."""
    for hook in _PROVISIONING_HOOKS:
        try:
            hook(ctx)
        except Exception:
            logger.exception("Provisioning hook '%s' failed", getattr(hook, "__name__", str(hook)))
            raise
