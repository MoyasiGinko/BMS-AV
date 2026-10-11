from __future__ import annotations

import importlib
from typing import Any

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integrations"
    verbose_name = "Integrations & Import/Export"

    def ready(self) -> None:
        events_mod = importlib.import_module("apps.core.events")
        services_mod = importlib.import_module("apps.integrations.services")

        @events_mod.subscribe("*")
        def _outbox_event_webhook_handler(event: Any) -> None:
            """Fan out processed outbox events to subscribed tenant webhooks."""
            if getattr(event, "organization_id", None):
                services_mod.dispatch_event_to_webhooks(
                    event_type=event.event_type,
                    event_id=str(event.event_id),
                    payload=getattr(event, "payload", {}) or {},
                    organization_id=event.organization_id,
                )
