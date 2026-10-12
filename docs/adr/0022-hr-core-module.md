# ADR 0022: HR Core Module Architecture

## Context
Phase 4 requires the People bundle starting with HR Core (employees, positions, department linkage, document management, status lifecycle, sensitive field encryption, and employee self-service). The platform already defines `Department` and `Branch` in `apps.tenancy` and `User` in `apps.accounts`.

## Decision
1. **Module Placement**: `apps.hr` resides at Layer 3 alongside `apps.sales` and `apps.purchasing` in `pyproject.toml`. It depends on `apps.tenancy` and `apps.core`, and is consumed by `apps.payroll` (Layer 2) and `apps.reports` (Layer 1).
2. **Encrypted Fields**: National ID and bank account details are stored encrypted at rest using AES-128-CBC / HMAC-SHA256 via `cryptography.fernet.Fernet` (`apps.core.crypto`), derived from `SECRET_KEY`. Decryption is restricted to `hr.view_sensitive` holders; masked representations (`**** 1234`) are rendered by default.
3. **State Lifecycle**: Strict state machine on `Employee` (`draft -> active -> on_leave | suspended -> terminated`) with transition validations and transactional outbox events.
4. **Self-Service**: Any authenticated user linked to an `Employee` profile can access `/hr/me/` and `/api/v1/hr/me/` to view and update permitted self-service fields (personal email, phone, emergency contacts) without requiring administrative HR permissions.

## Consequences
- Complies with Layer 3 architecture contracts.
- High security for PII and financial records.
- Seamless foundation for P4-03 Attendance and P4-04 Payroll.
