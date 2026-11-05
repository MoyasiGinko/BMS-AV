from django.db import migrations


def migrate_to_superadmin_hierarchy(apps, schema_editor):
    Organization = apps.get_model("tenancy", "Organization")
    Role = apps.get_model("tenancy", "Role")
    Membership = apps.get_model("tenancy", "Membership")

    for org in Organization.objects.all():
        # 1. Ensure Superadmin role exists with is_system=True and permissions=['*']
        superadmin_role = Role.objects.filter(
            organization=org,
            name__iexact="superadmin",
        ).first()

        if not superadmin_role:
            # Check for legacy Owner role to rename or convert
            legacy_owner_role = Role.objects.filter(
                organization=org,
                name__iexact="owner",
            ).first()
            if legacy_owner_role:
                legacy_owner_role.name = "Superadmin"
                legacy_owner_role.is_system = True
                legacy_owner_role.permissions = ["*"]
                legacy_owner_role.save(update_fields=["name", "is_system", "permissions"])
                superadmin_role = legacy_owner_role
            else:
                superadmin_role = Role.objects.create(
                    organization=org,
                    name="Superadmin",
                    description="Highest authority from user perspective with full unrestricted access to all modules and branches.",
                    is_system=True,
                    permissions=["*"],
                )
        else:
            superadmin_role.is_system = True
            superadmin_role.permissions = ["*"]
            superadmin_role.save(update_fields=["is_system", "permissions"])

        # 2. Assign Superadmin role to all owners and legacy owner/admin roles
        Membership.objects.filter(
            organization=org,
            is_owner=True,
        ).update(role=superadmin_role)

        # 3. Convert all other roles to dynamic (is_system=False)
        Role.objects.filter(
            organization=org,
        ).exclude(
            pk=superadmin_role.pk,
        ).update(is_system=False)


def reverse_superadmin_hierarchy(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0007_usernotificationpreference"),
    ]

    operations = [
        migrations.RunPython(
            migrate_to_superadmin_hierarchy,
            reverse_code=reverse_superadmin_hierarchy,
        ),
    ]

