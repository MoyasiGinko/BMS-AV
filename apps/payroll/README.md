# Payroll Module (`apps.payroll`)

## Overview
The Payroll module provides comprehensive compensation management, salary structures, earnings and deductions catalog, period calculation runs, employee payslip generation, PDF receipt generation, and double-entry accounting ledger integrations (accrual posting on approval, cash disbursement on payout, and reversal entries on cancellation).

## Architectural Placement
- **Layer**: Layer 2 (`apps.pos | apps.payroll | apps.crm`).
- **Dependencies**:
  - `apps.core`: Base models (`TenantModel`), outbox domain event publishing, tenant context.
  - `apps.tenancy`: Organization and Branch linkages.
  - `apps.hr`: Employee records (`apps.hr.models.Employee`), leave records (`LeaveRequest`).
  - `apps.accounting`: General Ledger accounts and transactional double-entry journal entries (`JournalEntry`, `JournalEntryLine`).
- **Invariants**:
  - Strict tenant isolation on every model, manager, query, and mutation.
  - All monetary values stored as `Decimal` (`DecimalField(max_digits=12, decimal_places=2)`), never float.
  - Double-entry balance guarantee: Every payroll run approval posts a balanced journal entry (dr: Salary Expense, cr: Payroll Payable & Tax Withholding).
  - Immutability & Reversals: Approved/paid runs cannot be edited; cancellations generate reverse journal entries.
  - Transactional state changes wrapped in `@transaction.atomic` that publish domain events.

## Core Models
- `SalaryComponent`: Catalog of pay elements (Basic, Housing, Transport, Tax Withholding, Health Insurance) categorized as `earning` or `deduction`.
- `SalaryStructure`: Reusable compensation package templates combining components via calculation formulas (`fixed` amount or `percent_of_basic`).
- `SalaryStructureItem`: Individual component formula attached to a structure.
- `EmployeeSalaryAssignment`: Active compensation package and base salary rate assigned to an employee.
- `PayrollRun`: Periodic calculation batch (e.g. Monthly) with lifecycle states (`draft` -> `reviewed` -> `approved` -> `paid` -> `cancelled`).
- `Payslip`: Itemized employee receipt for a specific run calculating gross earnings, deductions, unpaid leave penalties, and net payable.
- `PayslipItem`: Itemized line item on a payslip specifying component breakdown.

## Key Services
- `create_salary_component(...)` / `update_salary_component(...)`
- `create_salary_structure(...)` / `update_salary_structure(...)` / `add_structure_item(...)` / `remove_structure_item(...)`
- `assign_employee_salary(...)`: Maps employee to structure and base salary rate.
- `create_payroll_run(...)`: Calculates period earnings, deducts approved unpaid leave days, and creates draft payslips.
- `review_payroll_run(...)`: Transitions draft run to reviewed status.
- `approve_payroll_run(...)`: Approves calculation run and automatically generates/posts the General Ledger accrual journal entry.
- `pay_payroll_run(...)`: Disburses payroll funds via payment account (Bank or Cash) and posts the disbursement journal entry.
- `cancel_payroll_run(...)`: Reverses any posted GL entries and marks the payroll run as cancelled.

## User Interface & HTMX
- `/payroll/runs/`: Historical payroll runs directory with status filtering and cost metrics.
- `/payroll/runs/new/`: Interactive period run generator with real-time employee inclusion counts.
- `/payroll/runs/<id>/`: Run calculation overview, itemized employee payslip table, and action triggers (Review, Approve, Disburse, Cancel).
- `/payroll/payslips/<id>/`: Individual employee payslip detail breakdown with earnings, deductions, and payment details.
- `/payroll/payslips/<id>/pdf/`: High-fidelity ReportLab PDF payslip receipt download.
- `/payroll/my-payslips/`: Employee self-service payslip history with one-click PDF downloads.
- `/payroll/structures/`: Company compensation packages and component formula builders.
- `/payroll/components/`: Earning and deduction component catalog.
- `/payroll/assignments/`: Employee compensation assignments directory.

## REST API
Versioned endpoints under `/api/v1/payroll/`:
- `/api/v1/payroll/runs/` (includes `POST /api/v1/payroll/runs/{id}/review/`, `POST /api/v1/payroll/runs/{id}/approve/`, `POST /api/v1/payroll/runs/{id}/pay/`, `POST /api/v1/payroll/runs/{id}/cancel/`)
- `/api/v1/payroll/payslips/` (includes `GET /api/v1/payroll/payslips/{id}/pdf/`)
- `/api/v1/payroll/structures/`
- `/api/v1/payroll/components/`
- `/api/v1/payroll/assignments/`
