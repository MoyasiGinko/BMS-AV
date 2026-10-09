import importlib

from django.apps import AppConfig


class PosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pos"
    verbose_name = "Point of Sale"

    def ready(self) -> None:
        perm_mod = importlib.import_module("apps.pos.permissions")
        perm_mod.register_pos_permissions()
