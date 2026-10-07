# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("billing_subscription"),
        enable_rls("billing_usagecounter"),
    ]
