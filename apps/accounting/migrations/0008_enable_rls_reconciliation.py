# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0007_add_reconciliation_audit_system"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("accounting_reconciliationdiscrepancy"),
        enable_rls("accounting_reconciliationaudittrail"),
        enable_rls("accounting_bankstatementimport"),
    ]

