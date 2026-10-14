# Generated for RLS enforcement on recurring invoice and payment reminder models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0006_creditnoteline_sales_credi_organiz_230125_idx_and_more"),
    ]

    operations = [
        enable_rls("sales_recurringinvoiceprofile"),
        enable_rls("sales_recurringinvoiceline"),
        enable_rls("sales_paymentreminderrule"),
        enable_rls("sales_paymentreminderlog"),
    ]
