# Generated manually for RLS enforcement on approvals tables

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("approvals", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("approvals_approvalrule"),
        enable_rls("approvals_approvalrequest"),
        enable_rls("approvals_approvalhistory"),
    ]
