# ADR 0026: People Modules Demo Seeding and Permissions Architecture

## Status
Accepted

## Context
Task P4-06 requires seeding realistic demonstration data for the People modules (CRM, HR core, Attendance & Leave, and Payroll) and verifying security permissions enforcing that HR and Payroll data is strictly restricted to authorized HR/Payroll personnel and organization owners.
Standard employees must have self-service access to their own profile, attendance check-in, leave requests, and payslips without exposure to organizational staff records, sensitive encrypted PII, other employees' compensation, or organizational payroll accounting.

## Decision
1. Extend `apps.core.management.commands.seed_demo` to seed complete People workflows for the demo organization (`Apex Industrial Wholesale`):
   - Provision dedicated demo personas:
     - `hr.manager@apex.com`: HR Manager with `hr.*`, `reports.view`, and `hr.view_sensitive`.
     - `payroll@apex.com`: Payroll Accountant with `payroll.*`, `reports.view`.
     - `sarah.dev@apex.com`: Senior Engineer with standard Member role (Self-service access only).
     - `alex.rep@apex.com`: Sales Representative with CRM agent role (`crm.*`).
   - Seed CRM pipelines, stages, leads, opportunities, interactions, and follow-up tasks.
   - Seed HR departments, job positions, work shifts, employee profiles with encrypted sensitive PII, direct report hierarchies, and employment records.
   - Seed past and current attendance logs (clock-in/out, late arrivals, calculated work hours), leave policy types, yearly employee leave quotas, and approved leave requests.
   - Seed payroll salary components, tiered salary structures, employee salary assignments, and two payroll runs (past paid run with posted GL accounting entries and current active run with payslips).
2. Authorize `seed_demo` exemptions in `pyproject.toml` under the "Module layering" contract per ADR 0019 for importing `apps.crm`, `apps.hr`, and `apps.payroll` services and models.
3. Implement `tests/test_people_permissions.py` validating three-tier security boundaries:
   - Full organizational HR and Payroll management restricted to users with `hr.view` / `payroll.view` or Organization Owner.
   - Sensitive PII masked for staff lacking `hr.view_sensitive`.
   - Employee self-service strictly scoped to the authenticated user's own linked employee profile.
   - Cross-tenant and cross-employee horizontal privilege escalation completely blocked.

## Consequences
- Demonstrations and tests have rich, realistic organizational human capital data out of the box (`make seed`).
- The multi-tenant security model guarantees zero leakage of employee PII or compensation data.
- Architecture layer contracts in `pyproject.toml` remain 100% clean and enforced.
