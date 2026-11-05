# Generated manually for RLS enforcement on multi-location tables

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0006_multi_location_inventory_architecture"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("inventory_inventorylocation"),
        enable_rls("inventory_stocksupplyroute"),
        enable_rls("inventory_inventoryreconciliationincident"),
    ]

