# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0004_bankaccount_bankreconciliation_banktransaction_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("accounting_bankaccount"),
        enable_rls("accounting_bankreconciliation"),
        enable_rls("accounting_banktransaction"),
        enable_rls("accounting_exchangerate"),
        enable_rls("accounting_expensecategory"),
        enable_rls("accounting_expense"),
        enable_rls("accounting_taxperiodsummary"),
    ]
