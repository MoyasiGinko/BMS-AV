# Generated manually for RLS enforcement on Portability, Retention, and GDPR models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0008_dataretentionpolicy_datasubjectrequest_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("integrations_tenantexportjob"),
        enable_rls("integrations_tenantimportjob"),
        enable_rls("integrations_dataretentionpolicy"),
        enable_rls("integrations_datasubjectrequest"),
    ]
