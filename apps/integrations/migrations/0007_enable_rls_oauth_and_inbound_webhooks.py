# Generated manually for RLS enforcement on OAuth and Inbound Webhook models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0006_inboundwebhookendpoint_inboundwebhooklog_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("integrations_oauth_application"),
        enable_rls("integrations_inboundwebhookendpoint"),
        enable_rls("integrations_inboundwebhooklog"),
    ]
