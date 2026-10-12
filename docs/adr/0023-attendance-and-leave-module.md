# ADR 0023: Attendance & Leave Management Architecture

## Context
Backlog task P4-03 requires shifts, attendance tracking (check-in/check-out via Web UI and REST API), leave types, leave balance accounting, leave requests and approval workflows, and an attendance/leave calendar.

## Decision
1. **Module Placement**: Extend `apps.hr` (Layer 3) to encompass Attendance & Leave subdomains rather than creating separate fragmented apps. This maintains cohesive employee lifecycle boundaries and adheres to `pyproject.toml` import-linter rules.
2. **Domain Models**:
   - `Shift`: Work schedule templates (start_time, end_time, break_minutes, overnight support, active flag).
   - `AttendanceRecord`: Employee check-in/out log with date, check-in/out timestamps, calculation of net work hours, tracking source (`web`, `api`, `kiosk`, `manual`), and status (`present`, `late`, `half_day`, `absent`, `on_leave`).
   - `LeaveType`: Organization leave category policy (code, name, is_paid, default_allowance_days, requires_approval).
   - `LeaveBalance`: Per-employee, per-leave-type, per-year ledger of allocated, used, and pending days with automated balance checks.
   - `LeaveRequest`: Employee leave applications with state machine (`pending -> approved | rejected | cancelled`, and `approved -> cancelled`). Approval automatically credits used days on `LeaveBalance` and updates employee status if current date matches.
3. **Concurrency & Atomicity**: Check-in, check-out, leave submission, and approval execute within `@transaction.atomic` using `select_for_update()` on records and leave balances to prevent race conditions (e.g. double check-in or over-drafting leave balance).
4. **Calendar & Reporting Selectors**: Add unified calendar selectors to aggregate attendance events and approved leave intervals for both management oversight and employee self-service.
5. **REST API & Self-Service**:
   - Administrative endpoints under `/api/v1/hr/shifts/`, `/api/v1/hr/attendance/`, `/api/v1/hr/leave-types/`, `/api/v1/hr/leave-balances/`, `/api/v1/hr/leave-requests/`.
   - Employee self-service actions for personal check-in/check-out, personal leave balances, personal leave requests, and calendar feed.

## Consequences
- Single unified domain model for human resources, attendance, and leave.
- Clean foundation for P4-04 (Payroll) which can query `AttendanceRecord` and `LeaveRequest` for accurate salary deductions and allowances.
