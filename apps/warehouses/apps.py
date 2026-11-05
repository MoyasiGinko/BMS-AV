"""Django AppConfig for the Warehouses module."""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WarehousesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.warehouses"
    verbose_name = _("Warehouses")

