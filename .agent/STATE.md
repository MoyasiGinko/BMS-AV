# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-00
- Next task: P2-01
- Open `[!]` tasks: none
- Last `make verify`: PASSED (88.38% test coverage, 221 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-00 implemented the minimal accounting core (`apps.accounting`) with double-entry General Ledger primitives (`Account`, `AccountMapping`, `FiscalYear`, `FiscalPeriod`, `JournalEntry`, `JournalLine`), strict `Decimal(18, 4)` precision, immutable posted transactions with reversal workflows (`reverse_entry`), closed fiscal period protection (`PeriodClosed`), decoupled posting (`post_entry`, `Dr`, `Cr`), automated provisioning of chart of accounts and fiscal calendar via `provision_accounting` hook, and mathematical invariants tests with Hypothesis. Full quality gate passed with 221 tests green. Next task: P2-01 catalog (categories, units, tax codes, products, variants, barcodes, pricing, screens, API, CSV import/export).
