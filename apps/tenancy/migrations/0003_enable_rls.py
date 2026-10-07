# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0002_alter_organization_public_id_branch_department_and_more'),
        ('core', '0002_enable_rls'),
    ]

    operations = [
        enable_rls('tenancy_role'),
        enable_rls('tenancy_membership'),
        enable_rls('tenancy_branch'),
        enable_rls('tenancy_membershipbranch'),
        enable_rls('tenancy_department'),
        enable_rls('tenancy_warehouse'),
        enable_rls('tenancy_invitation'),
        enable_rls('tenancy_organizationsettings'),
    ]
