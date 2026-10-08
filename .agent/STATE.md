# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-03
- Next task: P2-04
- Open `[!]` tasks: none
- Last `make verify`: PASSED (88.55% test coverage, 301 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-03 implemented the complete Customers module (`apps.customers`) with customer CRUD, sequential customer numbering, addresses with primary shipping/billing flags, contact persons, immutable customer balance ledger (`CustomerBalanceEntry`), chronological running balances, credit limit checking with credit hold enforcement, print-ready and HTMX customer account statements, balance reconciliations, full HTMX interface, and versioned REST API under `/api/v1/customers/`. 39 customer tests added, including cross-tenant isolation and mathematical ledger chain invariants. Total test suite 301 tests passed at 88.55% coverage. Next task: P2-04 sales documents (quote -> order -> invoice -> credit note, document numbering, discounts, taxes, confirm service with stock effect posting through accounting core).
