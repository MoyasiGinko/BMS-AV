"""Core views for health checks and infrastructure status."""

from __future__ import annotations

import logging

from django.core.cache import caches
from django.db import connection
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)


def healthz_view(request: HttpRequest) -> JsonResponse:
    """Liveness probe: verifies web server process is responsive."""
    return JsonResponse({"status": "ok"})


def readyz_view(request: HttpRequest) -> JsonResponse:
    """Readiness probe: verifies PostgreSQL database and Redis connectivity."""
    checks: dict[str, str] = {}
    is_ready = True

    # 1. Database check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
            row = cursor.fetchone()
            if row and row[0] == 1:
                checks["database"] = "ok"
            else:
                checks["database"] = "unexpected_response"
                is_ready = False
    except Exception as err:
        logger.warning("Readiness probe database failure: %s", err)
        checks["database"] = f"error: {err}"
        is_ready = False

    # 2. Redis / Cache check
    try:
        cache = caches["default"]
        cache.set("_readyz_probe", "ok", 10)
        val = cache.get("_readyz_probe")
        if val == "ok":
            checks["cache"] = "ok"
        else:
            checks["cache"] = "cache_read_failure"
            is_ready = False
    except Exception as err:
        logger.warning("Readiness probe cache failure: %s", err)
        checks["cache"] = f"error: {err}"
        is_ready = False

    status_code = 200 if is_ready else 503
    return JsonResponse(
        {
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
        },
        status=status_code,
    )
