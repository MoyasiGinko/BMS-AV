# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("accounting_account"),
        enable_rls("accounting_accountmapping"),
        enable_rls("accounting_fiscalyear"),
        enable_rls("accounting_fiscalperiod"),
        enable_rls("accounting_journalentry"),
        enable_rls("accounting_journalline"),
    ]
