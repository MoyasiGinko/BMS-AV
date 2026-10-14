# Generated for RLS enforcement on HR models

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0002_leavetype_leaverequest_leavebalance_shift_and_more"),
    ]

    operations = [
        enable_rls("hr_position"),
        enable_rls("hr_shift"),
        enable_rls("hr_employee"),
        enable_rls("hr_employeedocument"),
        enable_rls("hr_attendancerecord"),
        enable_rls("hr_leavetype"),
        enable_rls("hr_leavebalance"),
        enable_rls("hr_leaverequest"),
    ]
