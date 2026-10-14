# Generated for RLS enforcement on Notification

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_notification"),
        ("core", "0005_enable_rls_apikey"),
    ]

    operations = [
        enable_rls("core_notification"),
    ]
