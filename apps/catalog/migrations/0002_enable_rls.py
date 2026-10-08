# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("catalog_category"),
        enable_rls("catalog_unit"),
        enable_rls("catalog_unitconversion"),
        enable_rls("catalog_product"),
        enable_rls("catalog_productvariant"),
        enable_rls("catalog_productimage"),
        enable_rls("catalog_pricelist"),
        enable_rls("catalog_pricelistitem"),
    ]
