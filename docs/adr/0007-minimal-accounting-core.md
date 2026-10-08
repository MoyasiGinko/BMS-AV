# ADR 0007: Minimal Accounting Core Architecture

## Context
Phase P2 introduces the operational modules (Catalog, Inventory, Customers, Sales, POS). Every commercial document that moves money or stock must post balanced double-entry accounting records (rule 30 and `ledger-posting` skill).
We need a minimal, rock-solid accounting core that manages the General Ledger, Chart of Accounts, Account Mappings, Fiscal Periods, and Journal Entries/Lines with guaranteed mathematical invariants.

## Decision
1. **Core Domain Entities**:
   - `Account`: Double-entry account (Asset, Liability, Equity, Revenue, Expense) with parent hierarchy and control account flag.
   - `AccountMapping`: Decouples business concepts (`sales.revenue`, `inventory.asset`, `cogs`, `ar`, `ap`, `tax.output`, `cash`, `bank`, etc.) from specific chart codes.
   - `FiscalYear` & `FiscalPeriod`: Time boundaries for accounting books. Posting into a closed period strictly raises `PeriodClosed`.
   - `JournalEntry` & `JournalLine`: Immutable double-entry ledger records with denormalized debit/credit totals and DB-level CHECK constraints.
2. **Double-Entry Balance & Precision**:
   - Monetary values stored strictly as `DecimalField(max_digits=18, decimal_places=4)`.
   - Debits == Credits invariant validated in `post_entry` service and protected by DB check constraint on posted entries (`total_debit == total_credit > 0`).
   - Line-level constraints enforce positive non-zero amounts and mutually exclusive debit/credit assignment.
3. **Immutability & Corrections**:
   - Posted journal entries are strictly immutable. Corrections are performed via `reverse_entry`, which creates a symmetrical reversal entry swapping debits and credits and transitions the original entry status to `reversed`.
4. **Decoupled Service Interface**:
   - `post_entry` accepts lines with `Account` objects, account codes, or mapping keys, utilizing `Dr(...)` and `Cr(...)` helper constructors.
   - Accounting never imports domain modules (Sales, Purchasing, Inventory, Payroll); documents link via `(source_type, source_id)` generic references.
5. **Automated Tenant Provisioning**:
   - Registered provisioning hook (`provision_accounting`) automatically seeds a standard chart of accounts, standard account mappings, current fiscal year, and open monthly fiscal periods when a tenant is provisioned.
6. **Row-Level Security**:
   - All tenant accounting tables have PostgreSQL RLS enabled.

## Consequences
- Foundation for inventory valuation, sales invoicing, payments, customer ledger, and POS checkout is established.
- Cross-tenant data isolation and double-entry invariants are enforced by both application checks and database constraints.
