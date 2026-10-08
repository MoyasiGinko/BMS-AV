# Generated manually for RLS enforcement on payments

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0003_payment_paymentallocation_paymentrefund_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("sales_payment"),
        enable_rls("sales_paymentallocation"),
        enable_rls("sales_paymentrefund"),
    ]
