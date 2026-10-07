# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_processedwebhookevent_subscription_customer_id_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("billing_subscriptioninvoice"),
    ]
