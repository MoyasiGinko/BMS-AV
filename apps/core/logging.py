"""Structured JSON logging and observability processors for Business OS.

Enriches logs with:
- timestamp (ISO 8601 UTC)
- request_id (propagated from RequestIdMiddleware)
- organization_id (tenant context)
- user_id (authenticated actor)
- logger, level, message, and exception stack traces
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from apps.core.tenant_context import (
    get_current_organization_id,
    get_current_request_id,
    get_current_user_id,
)

STANDARD_LOG_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JSONLogFormatter(logging.Formatter):
    """Formats log records as structured single-line JSON with tenant/request context."""

    def format(self, record: logging.LogRecord) -> str:
        # Standard record message
        message = record.getMessage()

        # UTC timestamp
        now = datetime.datetime.now(datetime.UTC).isoformat()

        # Context enrichment
        req_id = getattr(record, "request_id", None) or get_current_request_id()
        org_id = getattr(record, "organization_id", None) or get_current_organization_id()
        user_id = getattr(record, "user_id", None) or get_current_user_id()

        payload: dict[str, Any] = {
            "timestamp": now,
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": str(req_id) if req_id is not None else None,
            "organization_id": org_id,
            "user_id": user_id,
        }

        # Exception info
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exception"] = record.exc_text

        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # Extra attributes passed via logger.info("...", extra={...})
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in STANDARD_LOG_ATTRS and k not in ("request_id", "organization_id", "user_id")
        }
        if extras:
            payload["extra"] = extras

        return json.dumps(payload, default=str)


def add_observability_context(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Structlog processor to bind ambient tenant and request context."""
    if "request_id" not in event_dict:
        req_id = get_current_request_id()
        if req_id is not None:
            event_dict["request_id"] = str(req_id)

    if "organization_id" not in event_dict:
        org_id = get_current_organization_id()
        if org_id is not None:
            event_dict["organization_id"] = org_id

    if "user_id" not in event_dict:
        user_id = get_current_user_id()
        if user_id is not None:
            event_dict["user_id"] = user_id

    return event_dict
