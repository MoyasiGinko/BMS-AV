# ADR 0025: HR and Payroll Reports and Dashboard Widgets

## Context
Task P4-05 requires operational reports and real-time dashboard widgets for the People modules (Human Resources and Payroll). The platform dashboard employs a pluggable widget registry (`apps.core.dashboard.registry`) with plan entitlement, role permission, and dynamic visibility checks. Operational reports and export jobs (CSV, XLSX, PDF) are centralized in `apps.reports`.

## Decision
1. Implement 4 new dashboard widgets in `apps.reports.dashboard_widgets`:
   - `HeadcountWidget` (`headcount`): Active employee headcount, new hires, departures, and department breakdown (`hr.view`, module `hr`).
   - `AttendanceWidget` (`attendance`): Today's workforce presence, late check-ins, active leaves, and attendance rate (`hr.view`, module `hr`).
   - `PayrollCostWidget` (`payroll_cost`): Recent payroll expenditure, gross vs net breakdown, deduction totals, and compensation averages (`payroll.view`, module `payroll`).
   - `EmployeePerformanceWidget` (`employee_performance`): Attendance reliability ratings, punctuality scorecards, and tenure milestones (`hr.view`, module `hr`).
2. Add corresponding operational reports and background export types to `ReportType` in `apps.reports.models`:
   - `headcount`: Detailed staff roster, status distribution, and department turnover.
   - `attendance`: Workforce attendance records, late arrivals, shift scheduled vs worked, and leave utilization.
   - `payroll_cost`: Aggregated payroll run expenditures, deductions, and department salary distributions.
   - `employee_performance`: Punctuality metrics, attendance reliability tiering, and tenure tracking.
3. Centralize selectors in `apps.reports.selectors` (Layer 1) querying domain models from `apps.hr` and `apps.payroll` (Layer 2 / Layer 3) in full compliance with the module layering contract.
4. Provide responsive, accessible UI screens in `templates/reports/` and widget cards in `templates/reports/widgets/` with HTMX partial refresh support.

## Consequences
- Operators gain immediate visibility into staff attendance, organizational headcount, payroll expenditures, and punctuality performance.
- Background asynchronous exports (CSV, Excel, PDF) are supported out of the box for all HR and Payroll reports.
- Architecture contracts remain strictly preserved: `apps.reports` imports lower-layer modules (`apps.hr`, `apps.payroll`) without circular or forbidden imports.
