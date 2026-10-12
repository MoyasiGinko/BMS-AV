# Human Resources Module (`apps.hr`)

## Overview
The HR Core module provides end-to-end workforce lifecycle management, organizational structuring, encrypted sensitive PII storage, employee document repository, work shift schedules, time and attendance tracking, and paid/unpaid leave policy administration with balance tracking and multi-tier approval workflows.

## Architectural Placement
- **Layer**: Layer 3 (`apps.sales | apps.purchasing | apps.hr`).
- **Dependencies**:
  - `apps.core`: Base models (`TenantModel`), outbox domain event publishing, tenant context, field-level encryption (`apps.core.crypto`).
  - `apps.tenancy`: Organization, Department, Branch, and Membership linkages.
  - `apps.accounts`: Global User model linking employee self-service accounts.
- **Invariants**:
  - Strict tenant isolation on every model, manager, query, and mutation.
  - Sensitive employee fields (`national_id`, `bank_account`) encrypted at rest via symmetric Fernet keys.
  - Granular permission boundaries: standard HR data requires `hr.view`; sensitive PII unmasking strictly gated behind `hr.view_sensitive`.
  - Transactional state changes wrapped in `@transaction.atomic` that publish domain events.

## Core Models
- `Department`: Organizational business unit / cost center (from `apps.tenancy`).
- `Position`: Job role catalog with salary bands (`min_salary`, `max_salary`).
- `Shift`: Work shifts defining expected start/end times, break allowances, and overnight indicators.
- `Employee`: Complete employee dossier with encrypted PII, reporting manager hierarchy, linked user account, and lifecycle states (`draft`, `active`, `on_leave`, `suspended`, `terminated`).
- `EmployeeDocument`: Attached employment contracts, certifications, or scans with expiry tracking.
- `AttendanceRecord`: Clock-in/out records with source tracking (`web`, `mobile`, `kiosk`), duration calculation, and status flags (`present`, `late`, `early_departure`, `half_day`, `absent`).
- `LeaveType`: Leave policy categories (Annual, Sick, Maternity, Unpaid) with allowance limits and approval requirements.
- `LeaveBalance`: Per-employee annual leave quotas, accrued days, utilized days, and pending reservation.
- `LeaveRequest`: Employee leave applications with lifecycle states (`pending`, `approved`, `rejected`, `cancelled`).

## Key Services
- `create_employee(...)` / `update_employee(...)` / `transition_employee_status(...)`: Lifecycle state progression adhering to `ALLOWED_TRANSITIONS`.
- `update_employee_self_service(...)`: Self-service profile updates restricted to personal contact details.
- `upload_employee_document(...)` / `delete_employee_document(...)`
- `create_position(...)` / `update_position(...)`
- `create_shift(...)` / `update_shift(...)`
- `record_check_in(...)` / `record_check_out(...)` / `record_manual_attendance(...)`
- `create_leave_type(...)` / `allocate_leave_balance(...)`
- `submit_leave_request(...)` / `approve_leave_request(...)` / `reject_leave_request(...)` / `cancel_leave_request(...)`

## User Interface & HTMX
- `/hr/employees/`: Employee directory with instant search, department filtering, and status badges.
- `/hr/employees/<id>/`: Complete employee profile dossier with masked/unmasked PII toggles and document uploads.
- `/hr/me/`: Employee self-service dashboard with personal profile, quick punch in/out, leave balance cards, and recent attendance logs.
- `/hr/attendance/`: Daily workforce attendance logs, late flags, and attendance overview metrics.
- `/hr/attendance/check-in/` & `/hr/attendance/check-out/`: Quick clock-in/out endpoints.
- `/hr/leave-requests/`: Company-wide leave applications with one-click approve/reject actions.
- `/hr/leave-requests/new/`: Self-service leave application form.
- `/hr/leave-types/` & `/hr/leave-balances/`: Policy and annual quota allocation management.
- `/hr/positions/` & `/hr/shifts/`: Company organizational structure and shift roster catalog.

## REST API
Versioned endpoints under `/api/v1/hr/`:
- `/api/v1/hr/employees/` (includes `POST /api/v1/hr/employees/{id}/transition/`, `POST /api/v1/hr/employees/{id}/documents/`)
- `/api/v1/hr/me/`: Authenticated employee self-service profile.
- `/api/v1/hr/positions/`
- `/api/v1/hr/shifts/`
- `/api/v1/hr/attendance/` (includes `POST /api/v1/hr/attendance/check-in/`, `POST /api/v1/hr/attendance/check-out/`, `POST /api/v1/hr/attendance/manual/`)
- `/api/v1/hr/leave-types/`
- `/api/v1/hr/leave-balances/` (includes `POST /api/v1/hr/leave-balances/allocate/`)
- `/api/v1/hr/leave-requests/` (includes `POST /api/v1/hr/leave-requests/{id}/approve/`, `POST /api/v1/hr/leave-requests/{id}/reject/`)
