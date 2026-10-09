# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("purchasing", "0001_initial"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("purchasing_supplier"),
        enable_rls("purchasing_purchaseorder"),
        enable_rls("purchasing_purchaseorderline"),
        enable_rls("purchasing_goodsreceipt"),
        enable_rls("purchasing_goodsreceiptline"),
        enable_rls("purchasing_supplierbill"),
        enable_rls("purchasing_supplierbillline"),
        enable_rls("purchasing_supplierpayment"),
        enable_rls("purchasing_supplierpaymentallocation"),
        enable_rls("purchasing_purchasereturn"),
        enable_rls("purchasing_purchasereturnline"),
    ]
