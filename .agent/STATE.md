# Build State (updated by the agent after every task)

- Phase: P4 People: CRM + HR + Payroll
- Last completed task: P4-06
- Next task: P4-R Phase review
- Open `[!]` tasks: none
- Last `make verify`: PASSED (Full people test suite 91/91 passing including 8/8 comprehensive permissions and isolation tests, ruff clean, ruff format clean, makemigrations clean, django check clean, import-linter clean, spectacular OpenAPI validated, deploy check clean)
- Notes:
  - P4-06 seed_demo for people modules and permissions validation completed:
    - ADR 0026 documented demo seeding architecture and permission invariants for people modules.
    - Seeding Command: `apps/core/management/commands/seed_demo.py` extended with `--target people` support, provisioning realistic users and roles (`hr.manager@apex.com`, `payroll@apex.com`, `sarah.dev@apex.com`, `alex.rep@apex.com`), CRM pipelines/stages/leads/opportunities/tasks, HR departments/positions/shifts/employees with encrypted PII, attendance records, leave balances/requests, payroll components/structures/assignments, and historical paid runs with journal postings.
    - Permissions & Scoping: Authoring `tests/test_people_permissions.py` with 8 comprehensive integration tests:
      1. `test_hr_management_screens_access_control`: Owner & HR Manager access 200, unauthorized members get 403.
      2. `test_hr_management_api_access_control`: DRF endpoints return 200 for HR/Owner, 403 for unauthorized members.
      3. `test_payroll_management_screens_access_control`: Owner & Payroll Accountant access 200, unauthorized members get 403.
      4. `test_payroll_management_api_access_control`: DRF ViewSets return 200 for Payroll/Owner, 403 for unauthorized members.
      5. `test_sensitive_pii_masked_without_sensitive_permission`: Field-level encryption at rest; plaintext PII returned only with `hr.view_sensitive`, masked for standard viewers.
      6. `test_employee_self_service_workflows`: Self-service profile, punch check-in/out, leave applications, own payslip itemized view and PDF download.
      7. `test_cross_employee_payslip_isolation`: Employees blocked from viewing or downloading other employees' payslips.
      8. `test_cross_tenant_people_isolation`: Strict cross-tenant isolation on Web and REST API for all people models.
    - Architecture Quality: Fixed employee ownership lookup in `apps/payroll/views.py` and normalized `permission_map` in `apps/hr/api/views.py` and `HasRolePermission` in `apps/core/api/permissions.py`.
    - Verification: 91/91 people tests passing, `ruff check` and `ruff format` clean, `lint-imports` clean (2 kept, 0 broken), OpenAPI schema validated with 0 warnings, deploy checks clean.
  - Next task: P4-R Phase review.
