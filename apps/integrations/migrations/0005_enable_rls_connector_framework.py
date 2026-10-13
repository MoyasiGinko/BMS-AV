# Generated manually for RLS enforcement on Connector Framework models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0004_integrationconnection_externalreference_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("integrations_integrationconnection"),
        enable_rls("integrations_externalreference"),
        enable_rls("integrations_integrationsynclog"),
    ]
