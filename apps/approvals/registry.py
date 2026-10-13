from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ApprovalHandlerRegistry:
    """Decoupled handler registry for domain document updates on approval/rejection."""

    def __init__(self) -> None:
        self._handlers: dict[str, dict[str, Callable[..., Any]]] = {}

    def register(
        self,
        document_type: str,
        *,
        on_approve: Callable[..., Any],
        on_reject: Callable[..., Any] | None = None,
    ) -> None:
        """Register callbacks for a document_type."""
        self._handlers[document_type] = {
            "on_approve": on_approve,
            "on_reject": on_reject,
        }

    def get(self, document_type: str) -> dict[str, Callable[..., Any]] | None:
        return self._handlers.get(document_type)

    def clear(self) -> None:
        self._handlers.clear()


approval_handlers = ApprovalHandlerRegistry()
