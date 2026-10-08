# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("sales_quote"),
        enable_rls("sales_quoteline"),
        enable_rls("sales_salesorder"),
        enable_rls("sales_salesorderline"),
        enable_rls("sales_invoice"),
        enable_rls("sales_invoiceline"),
        enable_rls("sales_creditnote"),
        enable_rls("sales_creditnoteline"),
    ]
