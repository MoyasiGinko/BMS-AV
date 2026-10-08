# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("inventory_stocklevel"),
        enable_rls("inventory_stockmovement"),
        enable_rls("inventory_stockreservation"),
        enable_rls("inventory_stocktransfer"),
        enable_rls("inventory_stocktransferline"),
        enable_rls("inventory_stockadjustment"),
        enable_rls("inventory_stockadjustmentline"),
        enable_rls("inventory_stockcount"),
        enable_rls("inventory_stockcountline"),
    ]
