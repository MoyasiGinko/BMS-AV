"""Sentry error tracking integration for Business OS (env-gated)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sentry_sdk
from django.conf import settings
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from apps.core.tenant_context import (
    get_current_organization_id,
    get_current_request_id,
    get_current_user_id,
)

if TYPE_CHECKING:
    from sentry_sdk.types import Event, Hint

logger = logging.getLogger(__name__)


def _before_send(event: Event, hint: Hint) -> Event | None:
    """Tag and enrich Sentry events with tenant, request, and user context."""
    tags = event.setdefault("tags", {})
    extra = event.setdefault("extra", {})

    req_id = get_current_request_id()
    if req_id is not None:
        tags["request_id"] = str(req_id)
        extra["request_id"] = str(req_id)

    org_id = get_current_organization_id()
    if org_id is not None:
        tags["organization_id"] = str(org_id)
        extra["organization_id"] = org_id

    user_id = get_current_user_id()
    if user_id is not None:
        user_info = event.setdefault("user", {})
        user_info["id"] = str(user_id)

    return event


def init_sentry() -> bool:
    """Initialize Sentry SDK if SENTRY_DSN is configured in settings. Returns True if initialized."""
    dsn = getattr(settings, "SENTRY_DSN", "")
    if not dsn:
        return False

    try:
        environment = getattr(settings, "ENVIRONMENT", "production")
        sample_rate = getattr(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.1)

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                DjangoIntegration(),
                CeleryIntegration(),
                RedisIntegration(),
            ],
            before_send=_before_send,
            traces_sample_rate=sample_rate,
            send_default_pii=False,
            environment=environment,
        )
        logger.info("Sentry initialized successfully for environment '%s'", environment)
        return True
    except Exception as exc:
        logger.error("Failed to initialize Sentry: %s", exc)
        return False
