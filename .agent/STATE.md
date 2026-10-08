# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-04
- Next task: P2-05
- Open `[!]` tasks: none
- Last `make verify`: PASSED (87.90% test coverage, 328 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-04 implemented the complete Sales & Invoicing module (`apps.sales`) covering the full sales document lifecycle: Quotations (draft, sent, accepted, rejected, converted), Sales Orders (draft, confirmed, fulfilled, cancelled), Sales Invoices (draft, posted, partially paid, paid, void), and Credit Notes (draft, posted, void). Features include automated sequential document numbering (QT-, SO-, INV-, CN-), multi-currency support with exchange rates, multi-warehouse support, automated line-level discounting and tax calculations, strict atomic posting logic linking into General Ledger double-entry journals, inventory stock issuance/restock via average cost valuation, and customer balance subledger charges/credits. Shipped with complete HTMX-driven list, create, update, detail, and print views, plus versioned REST API endpoints under `/api/v1/sales/` with OpenAPI schemas and full test suite (unit, services, views, API, tenant isolation, and mathematical/financial invariants). Total test suite 328 tests passed at 87.90% coverage. Next task: P2-05 payments (customer payments, allocations to invoices, partial/over payments, refunds; balance + journal effects).

