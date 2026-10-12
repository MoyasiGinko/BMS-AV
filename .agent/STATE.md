# Build State (updated by the agent after every task)

- Phase: P4 People: CRM + HR + Payroll
- Last completed task: P4-05
- Next task: P4-06
- Open `[!]` tasks: none
- Last `make verify`: PASSED (Reports test suite 91/91 passing including 12/12 HR & Payroll report tests, OpenAPI schema validated, import-linter clean, ruff clean)
- Notes:
  - P4-05 HR/Payroll reports + dashboard widgets completed:
    - Selectors: `get_headcount_kpi`, `get_headcount_report`, `get_workforce_attendance_kpi`, `get_workforce_attendance_report`, `get_payroll_cost_kpi`, `get_payroll_cost_report`, `get_employee_performance_kpi`, `get_employee_performance_report`.
    - ADR 0025 documented HR & Payroll reports and widget registry architecture in `apps.reports`.
    - Dashboard Widgets: `HeadcountWidget`, `AttendanceWidget`, `PayrollCostWidget`, `EmployeePerformanceWidget` registered in global widget registry with role permissions (`hr.view`, `payroll.view`) and feature entitlements (`hr`, `payroll`).
    - Templates: 4 widget partials in `templates/reports/widgets/` with HTMX partial refresh, and 4 dedicated operational reports in `templates/reports/` with responsive tables, filters, and background export modals.
    - Export Machinery: RFC 4180 CSV, formatted Excel (XLSX), and ReportLab PDF document export generation implemented in `apps/reports/exporters.py` and queued via Celery in `apps/reports/services.py`.
    - Reports Hub: Updated `templates/reports/index.html` with the Human Resources & Payroll report directory.
    - Verification: 91/91 reports tests passing, `lint-imports` clean (2 kept, 0 broken), `manage.py spectacular --validate --fail-on-warn` passed with 0 warnings.
  - Next task: P4-06 seed_demo for people modules; permissions tests (HR data visible only to HR/owner).
