# Generated manually for RLS enforcement on reporting engine models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0005_alter_exportjob_report_type_savedreport_and_more"),
        ("core", "0002_enable_rls"),
    ]

    operations = [
        enable_rls("reports_savedreport"),
        enable_rls("reports_reportschedule"),
        enable_rls("reports_dailysalessummary"),
        enable_rls("reports_dailyexpensesummary"),
        enable_rls("reports_dashboardlayout"),
    ]
