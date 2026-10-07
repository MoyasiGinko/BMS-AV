"""Pluggable usage recording hooks for core requests and operations.

Allows higher-layer billing modules to meter usage without violating
architecture layering contracts.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_HANDLERS: dict[str, Any] = {
    "recorder": None,
    "reader": None,
}


def register_usage_recorder(callback: Callable[[int, str, int], None]) -> None:
    """Register a callback to receive metric increments."""
    _HANDLERS["recorder"] = callback


def register_usage_reader(callback: Callable[[int, str], int]) -> None:
    """Register a callback to read current metric counts."""
    _HANDLERS["reader"] = callback


def record_metric(organization_id: int, metric: str, amount: int = 1) -> None:
    """Record metric usage if a recorder is registered."""
    recorder = _HANDLERS.get("recorder")
    if recorder is not None:
        try:
            recorder(organization_id, metric, amount)
        except Exception:
            logger.exception("Failed to record metric '%s' for org %s", metric, organization_id)


def get_metric_count(organization_id: int, metric: str) -> int:
    """Read metric count for the current calendar period."""
    reader = _HANDLERS.get("reader")
    if reader is not None:
        try:
            return int(reader(organization_id, metric))
        except Exception:
            logger.exception("Failed to read metric '%s' for org %s", metric, organization_id)
    return 0
