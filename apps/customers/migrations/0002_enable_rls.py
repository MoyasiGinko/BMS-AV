# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("customers_customer"),
        enable_rls("customers_customeraddress"),
        enable_rls("customers_customercontact"),
        enable_rls("customers_customerbalanceentry"),
    ]
