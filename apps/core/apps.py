from django.apps import AppConfig

from apps.core.sentry import init_sentry


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self) -> None:
        init_sentry()
