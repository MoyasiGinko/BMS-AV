# Generated for RLS enforcement on Payroll models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0001_initial"),
    ]

    operations = [
        enable_rls("payroll_salarycomponent"),
        enable_rls("payroll_salarystructure"),
        enable_rls("payroll_salarystructureitem"),
        enable_rls("payroll_employeesalaryassignment"),
        enable_rls("payroll_payrollrun"),
        enable_rls("payroll_payslip"),
        enable_rls("payroll_payslipitem"),
    ]
