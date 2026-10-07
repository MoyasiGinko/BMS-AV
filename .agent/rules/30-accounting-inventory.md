---
trigger: model_decision
description: Use when touching accounting, journals, payments, invoices, bills, stock, costing, purchasing, sales, POS, payroll posting, or any money/quantity logic.
---
# Accounting & Inventory Rules

## Money
- `Decimal` everywhere (`DecimalField(max_digits=18, decimal_places=4)` for amounts, 4 dp for quantity/cost, round only at presentation
  or by documented rounding rules). Store currency, `base_amount` and `fx_rate` on transactional lines.
- Double-entry: `JournalEntry` + `JournalLine`. Sum(debit) == Sum(credit) enforced in `accounting.services.post_entry` AND by a DB
  check/trigger on posted entries. Posted entries are immutable; reverse with `reverse_entry`.
- Fiscal periods can be closed; posting into a closed period raises `PeriodClosed`.
- Every financial document stores `journal_entry` and is referenced by `(source_type, source_id)` on the entry.
- Posting is done only by `accounting.services.post_*` functions called from the owning module's service, in the same transaction.
  Accounting never imports sales/purchasing/payroll (use `source_type` + generic refs).
- Account resolution uses an `AccountMapping` table (e.g. `sales.revenue`, `inventory.asset`, `cogs`, `ar`, `ap`, `tax.output`),
  seeded from a chart-of-accounts template at organization creation.

## Inventory
- `StockMovement` is the immutable ledger (product, warehouse, signed quantity, unit_cost, reference, timestamp). `StockLevel` is a
  cache updated only inside inventory services; a reconciliation job and test compare it to the ledger.
- Costing behind a `CostingStrategy` interface; start with weighted average. Reservations for confirmed undelivered orders.
- Transfers = two linked movements. Adjustments require a reason code. Negative stock is an org setting (default off).

## Document flows (each = one service, one transaction, one event)
- Sale confirm / POS checkout: stock out (+COGS) -> invoice -> journal (AR/cash, revenue, tax, COGS/inventory) -> customer balance -> payment if tendered.
- Sale return: stock in at original cost -> credit note -> reversing journal -> balance.
- Purchase receipt: stock in at cost -> supplier bill -> journal (inventory/GRNI, AP) -> supplier balance.
- Payments/allocations, expenses, payroll approval, stock adjustment/transfer: same pattern.
- Invariants to test with hypothesis: debits==credits; stock level == ledger sum; AR subledger == AR account; AP == AP account;
  inventory subledger value == inventory account; trial balance balances; reports reconcile to ledgers.
