# Build State (updated by the agent after every task)

- Phase: P2 Small-shop MVP (in progress)
- Last completed task: P2-05
- Next task: P2-06
- Open `[!]` tasks: none
- Last `make verify`: PASSED (87.54% test coverage, 340 tests green, all architecture contracts kept, openapi valid, deploy check clean)
- Notes: P2-05 implemented customer payments, allocations to invoices, partial/over payments, refunds, and void reversals within `apps.sales` (governed by ADR 0012). Highlights:
  - Models: Payment, PaymentAllocation, PaymentRefund with positive amount check constraints and strict allocation validity bounds.
  - PostgreSQL Row Level Security (RLS) enabled on all payment tables with tenant isolation policies.
  - Double-entry postings: Payment receives cash/bank debit and Accounts Receivable credit; customer subledger posts payment credits; invoice amount_paid, balance_due, and status (POSTED -> PARTIALLY_PAID -> PAID) update atomically.
  - Overpayments safely captured as unallocated customer advance deposits with ability to allocate to subsequent invoices or process customer refunds (Dr AR, Cr Cash).
  - Void reversals cleanly reinstate invoice balances, post GL reversal journals, and update customer subledger balances.
  - Full server-rendered templates with HTMX partials: payment list with metrics header, filter bar, create form with dynamic invoice allocation table, detail page with allocation & refund history, and printable payment receipt view.
  - Versioned REST API under `/api/v1/sales/payments/` with allocate, refund, and void actions.
  - Complete test coverage across services, views, REST API, tenant isolation, and mathematical/financial invariants (340 tests passed). Next task: P2-06 POS.
