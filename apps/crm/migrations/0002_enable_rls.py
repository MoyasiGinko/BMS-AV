# Generated for RLS enforcement on CRM models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0001_initial"),
    ]

    operations = [
        enable_rls("crm_pipeline"),
        enable_rls("crm_stage"),
        enable_rls("crm_tag"),
        enable_rls("crm_lead"),
        enable_rls("crm_opportunity"),
        enable_rls("crm_interaction"),
        enable_rls("crm_crmtask"),
    ]
