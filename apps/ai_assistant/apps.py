"""AppConfig for AI Assistant and Intelligence module."""

from __future__ import annotations

import importlib

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AiAssistantConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai_assistant"
    verbose_name = _("AI Assistant & Intelligence")

    def ready(self) -> None:
        dashboard_mod = importlib.import_module("apps.core.dashboard")
        widgets_mod = importlib.import_module("apps.ai_assistant.dashboard_widgets")
        dashboard_mod.register_widget(widgets_mod.AttentionTodayWidget())
