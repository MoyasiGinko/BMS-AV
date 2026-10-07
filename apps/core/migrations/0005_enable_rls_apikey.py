# Generated for RLS enforcement on ApiKey

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_apikey"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("core_apikey"),
    ]
