# Accounting Module (`apps.accounting`)

Minimal accounting core and general ledger engine for Business OS.

## Responsibilities
- **General Ledger Primitives**: `Account`, `AccountMapping`, `FiscalYear`, `FiscalPeriod`, `JournalEntry`, `JournalLine`.
- **Double-Entry Balance Invariants**: Guaranteed sum(debit) == sum(credit) > 0 on every posted transaction enforced in `post_entry` service and protected by DB check constraints.
- **Immutability & Audit Trail**: Posted entries are strictly immutable. Adjustments and cancellations are executed via symmetrical reversing entries (`reverse_entry`).
- **Fiscal Period Controls**: Strict period boundary checking; postings to closed fiscal periods/years reject immediately with `PeriodClosed`.
- **Decoupled Integration**: Operational modules (Sales, Purchasing, Inventory, Payroll) post via `accounting.services.post_entry` using semantic mapping keys (`sales.revenue`, `cogs`, `ar`, `ap`, etc.) and generic `(source_type, source_id)` references without cross-layer coupling.
- **Automated Tenant Provisioning**: Automatically seeds a standard chart of accounts, standard account mappings, fiscal year, and monthly open periods via `provision_accounting` hook.
