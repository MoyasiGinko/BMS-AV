# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-06
- Next task: P2-07
- Open `[!]` tasks: none
- Last `make verify`: PASSED (87.55% test coverage, 360 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-06 implemented full POS (Point of Sale) sub-system (governed by ADR 0013):
  - Models: POSRegister, POSShift (with opening float, cash count, cash variance tracking), POSHeldCart, and POSSale with multi-tender split payment logging.
  - PostgreSQL Row Level Security (RLS) enabled on all POS tables with tenant isolation policies.
  - Shift workflows: Opening float verification, cashier active shift locking, closing cash reconciliation posting GL suspense entries for cash variances.
  - POS Checkout service: Atomically generates and confirms sales invoices, moves stock via inventory issue lines, processes split tender payments (cash, card, mobile money, customer balance), updates drawer totals, and publishes domain events.
  - UI: Fast counter checkout 2-pane terminal with live category filter, product search, keypad/numpad, hold/resume cart, modal tender checkout, and 80mm printable thermal receipt. Shift list/detail/open/close views and register CRUD screens.
  - REST API: Endpoints under `/api/v1/pos/` with OpenAPI documentation and permission enforcement.
  - Tests: Comprehensive unit, views, API, tenant isolation, and financial/inventory invariants across shifts and sales (360 tests passed). Next task: P2-07 Dashboard widgets v1.
