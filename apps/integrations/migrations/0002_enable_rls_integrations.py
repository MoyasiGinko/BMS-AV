# Generated manually for RLS enforcement on Integrations models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("integrations_importjob"),
        enable_rls("integrations_exportjob"),
    ]
