# Build State (updated by the agent after every task)

- Phase: P4 People: CRM + HR + Payroll
- Last completed task: P4-03
- Next task: P4-04
- Open `[!]` tasks: none
- Last `make verify`: PASSED (HR test suite 39/39 passing, OpenAPI schema validated, import-linter clean, ruff clean)
- Notes:
  - P4-03 Attendance + Leave module completed:
    - Domain models: Shift, AttendanceRecord, LeaveType, LeaveBalance, LeaveRequest.
    - ADR 0023 documented Attendance and Leave module architecture in Layer 3 within `apps.hr`.
    - Services & State Machine: Shift scheduling, web/API clock-in/out, late arrival detection (>15m grace), manual attendance logging, yearly quota allocation, leave request submission/approval/rejection/cancellation with balance deductions.
    - Selectors: Attendance logs, active check-in discovery, daily workforce attendance summary metrics, yearly quota balances, and combined HR attendance & leave calendar event aggregation.
    - Web UI: Shift management, Attendance tracking table with status filtering and HTMX quick clock-in/out, Manual log modal/screen, Leave Types policy catalog, Leave Balances ledger, Leave Request approval queue, interactive monthly Calendar view, and enhanced employee Self-Service portal.
    - REST API: Versioned viewsets for `/api/v1/hr/shifts/`, `/api/v1/hr/attendance/` (with check-in/out/manual actions), `/api/v1/hr/leave-types/`, `/api/v1/hr/leave-balances/` (with quota allocation), `/api/v1/hr/leave-requests/` (with approve/reject/cancel actions), and `/api/v1/hr/calendar/`.
    - Tests: 39/39 unit, selector, view, API, and cross-tenant isolation tests passing.
  - Next task: P4-04 Payroll: salary structures/components, payroll run (draft -> review -> approve -> pay), payslips PDF, accounting posting (expense + liabilities + payable), expense linkage.
