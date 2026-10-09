# Generated manually for RLS enforcement on Reports

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("reports_exportjob"),
    ]
