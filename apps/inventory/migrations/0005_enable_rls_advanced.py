# Generated manually for RLS enforcement on advanced inventory tables

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0004_batchstock_serialnumber_stockcostlayer_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("inventory_batch"),
        enable_rls("inventory_batchstock"),
        enable_rls("inventory_serialnumber"),
        enable_rls("inventory_stockcostlayer"),
    ]
