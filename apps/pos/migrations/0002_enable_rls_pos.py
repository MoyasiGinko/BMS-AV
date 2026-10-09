# Generated manually for RLS enforcement on Point of Sale (POS)

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("pos", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("pos_posregister"),
        enable_rls("pos_posshift"),
        enable_rls("pos_posheldcart"),
        enable_rls("pos_possale"),
    ]
