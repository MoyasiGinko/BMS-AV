# Sales Module (`apps.sales`)

End-to-end B2B sales cycle, quoting, sales order processing, tax calculations, invoice posting, customer payments, allocations, and credit notes.

## Responsibilities
- **Document State Machines**:
  - `Quote` (`DRAFT` -> `SENT` -> `ACCEPTED` / `REJECTED` / `EXPIRED`)
  - `SalesOrder` (`DRAFT` -> `CONFIRMED` -> `PROCESSING` -> `COMPLETED` / `CANCELLED`)
  - `Invoice` (`DRAFT` -> `POSTED` -> `PARTIALLY_PAID` -> `PAID` / `CANCELLED`)
  - `CreditNote` (`DRAFT` -> `POSTED` -> `ALLOCATED`)
  - `Payment` & `PaymentAllocation`
- **Atomic Operations & Ledger Integration**:
  - `confirm_sales_order`: Validates stock availability and credit limits.
  - `post_invoice`: Dispatches physical stock from warehouse, creates double-entry journal postings (Debit AR, Credit Revenue, Credit Tax Payable, Debit COGS, Credit Inventory Asset), and increases customer balance.
  - `receive_payment` & `allocate_payment`: Reduces AR balance, records cash/bank ledger entries, and updates invoice paid statuses.
  - `post_credit_note`: Reverses sales revenue, recalculates balances, and issues credit allocations.
- **Idempotency Protection**: Mutating actions on sales orders, invoices, and payments enforce unique `Idempotency-Key` headers via Redis-backed cache locks.
- **Domain Events**: Publishes `sales.quote_created`, `sales.order_confirmed`, `sales.invoice_posted`, `sales.payment_received`, `sales.credit_note_posted`.
- **Interfaces**:
  - Full HTMX UI: document lifecycle views, inline line-item editors, partial payment modals, print-ready invoices.
  - REST API v1 (`/api/v1/sales/quotes/`, `/orders/`, `/invoices/`, `/payments/`, `/credit-notes/`).
- **Permissions**: Three-layer enforcement (sales entitlement, role permission, tenant scoping).
