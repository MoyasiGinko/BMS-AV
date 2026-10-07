# Generated for RLS enforcement on Currency, NotificationPreference, and TaxCode

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0004_currency_notificationpreference_taxcode"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("tenancy_currency"),
        enable_rls("tenancy_notificationpreference"),
        enable_rls("tenancy_taxcode"),
    ]
