# ADR 0024: Payroll Module Architecture and Double-Entry Ledger Posting

## Status
Accepted

## Context
Task P4-04 requires a complete multi-tenant Payroll module covering:
- Salary structures and components (earnings and deductions, fixed amounts or percentage formulas).
- Employee salary assignments (base salaries, effective date ranges, disbursement methods).
- Payroll run lifecycle with strict status state machine: `draft` -> `reviewed` -> `approved` -> `paid` (with rollback/cancellation).
- Automated payslip calculation incorporating employee structures, attendance records, and approved leaves.
- High-fidelity PDF payslip generation using ReportLab.
- Atomic double-entry accounting integration:
  - On approval: gross pay charged to `payroll.expense`, withholdings/deductions credited to `payroll.liability`, net pay credited to `payroll.liability`.
  - On payment: net pay debited from `payroll.liability` and credited to liquid assets (`bank` or `cash`).
  - Outbox domain events emitted for downstream integrations (`PayrollRunCreated`, `PayrollRunApproved`, `PayrollRunPaid`, `PayrollRunCancelled`).

## Decision
1. **Module Placement**: `apps.payroll` resides at Layer 2 alongside `apps.pos` and `apps.crm` in `pyproject.toml`. It imports `apps.hr` (Layer 3) for employee profiles, shifts, and leave records, and `apps.accounting` (Layer 4) for posting double-entry journals.
2. **Domain Models**:
   - `SalaryComponent`: code, name, type (`earning`, `deduction`), is_taxable, is_active.
   - `SalaryStructure`: code, name, description, is_active.
   - `SalaryStructureItem`: structure FK, component FK, amount, percentage, calculation_type (`fixed`, `percent_of_basic`).
   - `EmployeeSalaryAssignment`: employee FK, structure FK, base_salary, effective dates, payment details.
   - `PayrollRun`: number (`PAY-YYYYMM-XXXX` via NumberSequence), period dates, payment date, status machine (`draft`, `reviewed`, `approved`, `paid`, `cancelled`), totals, journal references, audit timestamps.
   - `Payslip`: run FK, employee FK, status, gross_pay, total_deductions, net_pay, payment info.
   - `PayslipItem`: payslip FK, component FK, type, amount.
3. **Double-Entry Accounting & Immutability**:
   - Payroll approval creates balanced `JournalEntry` via `accounting.services.post_entry`.
   - Payroll payment creates disbursement `JournalEntry`.
   - Cancellation of approved/paid runs executes reversing entries via `accounting.services.reverse_entry`.
4. **Delivery**:
   - Server-rendered templates + HTMX for runs, structures, components, assignments, payslips, and self-service.
   - ReportLab PDF generation for payslips.
   - Versioned REST API under `/api/v1/payroll/` with OpenAPI documentation and tenant scoping.

## Consequences
- Full compliance with `30-accounting-inventory` and `10-architecture` rules.
- Fully isolated multi-tenant execution without schema or query leakage.
