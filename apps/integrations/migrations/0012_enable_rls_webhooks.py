# Generated manually for RLS enforcement on webhook models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0011_remove_inboundwebhooklog_inbound_log_ep_created_idx_and_more"),
    ]

    operations = [
        enable_rls("integrations_webhookendpoint"),
        enable_rls("integrations_webhookdelivery"),
    ]
