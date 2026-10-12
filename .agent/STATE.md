# Build State (updated by the agent after every task)

- Phase: P4 People: CRM + HR + Payroll
- Last completed task: P4-02
- Next task: P4-03
- Open `[!]` tasks: none
- Last `make verify`: PASSED (HR test suite 26/26 passing, OpenAPI schema validated, import-linter clean, ruff clean)
- Notes:
  - P4-02 HR core module completed:
    - Domain models: Position, Employee, EmployeeDocument.
    - Security & Cryptography: AES Fernet encryption via `apps.core.crypto` for sensitive PII (national_id, tax_id, bank_account_number) with deterministic masking for safe display.
    - Status Lifecycle: Strict state transitions (`draft` -> `active` -> `on_leave` / `suspended` -> `terminated`) with terminal state enforcement and domain event publishing via outbox (`EmployeeHired`, `EmployeeStatusChanged`, `EmployeeTerminated`).
    - Self-Service Profile: Employee portal view and API endpoints allowing employees to securely view their profile and update permitted contact details.
    - DRF REST API: Position, Employee, Document, and Self-Service viewsets under `/api/v1/hr/` with tenant scoping and OpenAPI docs.
    - HTMX Web UI: Positions directory/editor, Employees directory with status/department filters, detailed employee cards, document upload/deletion, and self-service portal.
    - Test Suite: 26/26 passing tests across services, selectors, views, API, and cross-tenant isolation.
  - Next task: P4-03 Attendance + leave: shifts, check-in/out (web + API), leave types/balances/requests/approvals, calendar.
