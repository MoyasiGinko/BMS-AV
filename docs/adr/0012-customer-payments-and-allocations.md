# 0012. Customer Payments, Invoice Allocations, Refunds, and Journal Postings

Date: 2026-10-09

## Context
Phase P2-05 requires full support for customer payments, invoice allocations, partial and over-payments, refunds, and financial journal/ledger effects:
1. Customer payments against one or multiple posted sales invoices.
2. Support for partial payments (reducing invoice `balance_due`, marking invoice `PARTIALLY_PAID`), full payments (marking invoice `PAID`), and over-payments (excess funds held as `unallocated_amount` on customer account).
3. Prepayments / advance payments made before invoices are issued, with subsequent allocation when invoices are posted.
4. Customer refunds of unallocated payment balances or returns.
5. Payment methods (Cash, Bank Transfer, Credit Card, Debit Card, Check, Online, Other).
6. Double-entry General Ledger postings:
   - Payment: `Dr cash` / `Dr bank`, `Cr ar`.
   - Refund: `Dr ar`, `Cr cash` / `Cr bank`.
7. Customer subledger entries:
   - Payment: `CustomerBalanceEntry(entry_type=PAYMENT, credit=amount)`.
   - Refund: `CustomerBalanceEntry(entry_type=REFUND, debit=amount)`.
8. Voiding payments with reversal of GL entries, subledger adjustments, and restoration of invoice balances and statuses.
9. Domain events for transactional outbox: `PaymentReceived`, `PaymentAllocated`, `PaymentRefunded`, `PaymentVoided`.
10. Scoped tenant security, HTMX views, and versioned REST API endpoints under `/api/v1/sales/payments/`.

## Decision
1. **Module Placement**:
   - Payments are implemented within `apps.sales` as `Payment`, `PaymentAllocation`, and `PaymentRefund`, maintaining cohesive access to `Invoice` models and adhering to the architecture layer rules where `sales` mediates between operational documents and financial ledgers.
2. **Domain Models**:
   - `Payment`: scoped by tenant, customer, branch, payment_number (sequence `PMT-`), payment_date, payment_method, amount, allocated_amount, unallocated_amount, currency, exchange_rate, reference, status (`DRAFT`, `POSTED`, `VOID`), notes, and linked `JournalEntry`.
   - `PaymentAllocation`: links `Payment` to `Invoice` with allocated `amount` and timestamp.
   - `PaymentRefund`: scoped by tenant, payment, customer, refund_number (sequence `REF-`), refund_date, amount, reason, status, and linked `JournalEntry`.
3. **Services**:
   - `receive_payment`: `@transaction.atomic` with row locks on `Customer` and targeted `Invoice`s. Posts GL entry (`Dr cash/bank`, `Cr ar`), credits customer AR subledger, allocates to specified invoices, updates invoice `amount_paid`, `balance_due`, and status, records allocations, and publishes `PaymentReceived`.
   - `allocate_payment`: allocates unallocated funds from an existing payment to outstanding invoices.
   - `refund_payment`: `@transaction.atomic` refund of unallocated amount with GL entry (`Dr ar`, `Cr cash/bank`), debits customer subledger, and publishes `PaymentRefunded`.
   - `void_payment`: reverses GL entry, reverses customer subledger, restores invoice balances and statuses, and marks payment `VOID`.
4. **API and UI**:
   - HTMX screens: Payment list with filters, create payment modal/form with dynamic invoice allocation table, payment detail with allocation and GL breakdown, and receipt/print view.
   - REST API: `/api/v1/sales/payments/` with full CRUD, `/allocate/`, `/refund/`, and `/void/` actions.

## Consequences
- Strict financial consistency: GL control account `ar` always matches the sum of customer balances and outstanding invoice balances.
- Invoices transition accurately across `DRAFT -> POSTED -> PARTIALLY_PAID -> PAID`.
- Over-payments and advance deposits are accurately preserved on the customer's account.
