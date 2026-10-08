# 0011. Sales Document Lifecycle, Subledger Postings, and Stock Effects

Date: 2026-10-08

## Context
Phase P2 requires comprehensive sales lifecycle documents and transactions:
1. Four linked document types: Quotes (`Quote`), Sales Orders (`SalesOrder`), Sales Invoices (`Invoice`), and Credit Notes (`CreditNote`).
2. Document line items with quantities, pricing, discount percentages/amounts, and tax calculation.
3. Gapless per-organization document numbering sequences (`QT-`, `SO-`, `INV-`, `CN-`) via `generate_next_number`.
4. Document conversion flows: Quote -> Sales Order -> Sales Invoice, and Sales Invoice -> Credit Note.
5. Atomic posting of Sales Invoices with dual ledger effects:
   - Inventory movement: issuing stock at moving average cost via `inventory_services.issue_stock` (COGS calculation).
   - Double-entry accounting: posting balanced journal entry via `accounting_services.post_entry` (`Dr ar`, `Cr sales.revenue`, `Cr tax.output`, `Dr cogs`, `Cr inventory.asset`).
   - Customer subledger: applying AR balance charge via `customers_services.post_customer_transaction(entry_type=BalanceEntryType.INVOICE)`.
6. Atomic posting of Credit Notes:
   - Accounting reversal: `Dr sales.revenue`, `Dr tax.output`, `Cr ar`.
   - Restocking: receiving returned items back into stock at original unit cost via `inventory_services.receive_stock` (`Dr inventory.asset`, `Cr cogs`).
   - Customer subledger: applying balance credit via `customers_services.post_customer_transaction(entry_type=BalanceEntryType.CREDIT_NOTE)`.
7. Credit limit checks before order confirmation or invoice posting.
8. Scoped tenant security, HTMX UI screens with print layouts, and a versioned REST API under `/api/v1/sales/`.

## Decision
1. **Domain Models**:
   - `Quote`: scoped by tenant, customer, branch, warehouse, dates, status (`DRAFT`, `SENT`, `ACCEPTED`, `REJECTED`, `EXPIRED`, `CONVERTED`), subtotal, discounts, taxes, total, terms.
   - `QuoteLine`: product, optional variant, description, quantity, unit_price, discount_percent, discount_amount, tax_rate, tax_amount, line_total.
   - `SalesOrder`: scoped by tenant, customer, branch, warehouse, order_number, quote origin, status (`DRAFT`, `CONFIRMED`, `FULFILLED`, `CANCELLED`), order date, expected delivery, totals.
   - `SalesOrderLine`: product, variant, quantity, delivered_quantity, invoiced_quantity, unit_price, discounts, taxes, line_total.
   - `Invoice`: scoped by tenant, customer, branch, warehouse, invoice_number, sales_order origin, status (`DRAFT`, `POSTED`, `PARTIALLY_PAID`, `PAID`, `VOID`), invoice date, due date, totals, amount_paid, balance_due, and linked `JournalEntry`.
   - `InvoiceLine`: product, variant, description, quantity, unit_price, discounts, taxes, line_total.
   - `CreditNote`: scoped by tenant, customer, branch, warehouse, credit_note_number, invoice origin, status (`DRAFT`, `POSTED`, `VOID`), date, reason, totals, and linked `JournalEntry`.
   - `CreditNoteLine`: product, variant, description, quantity, unit_price, tax_rate, line_total, and `restock` boolean flag.
2. **Posting Service & Concurrency**:
   - `post_invoice` executes inside `@transaction.atomic` with row locks on `Invoice` and `Customer`.
   - Verifies customer status is not suspended and checks credit limits.
   - Issues stock for physical stock items via `inventory_services.issue_stock`.
   - Posts balanced double-entry journal entry via `accounting_services.post_entry`.
   - Posts customer balance entry with entry type `INVOICE`.
   - Publishes `InvoicePosted` domain event.
3. **Credit Note Service**:
   - `post_credit_note` executes inside `@transaction.atomic` with row locks on `CreditNote` and `Customer`.
   - Optionally restocks items back into inventory via `inventory_services.receive_stock`.
   - Posts balanced reversing journal entry.
   - Posts customer balance entry with entry type `CREDIT_NOTE`.
   - Publishes `CreditNotePosted` domain event.
4. **Number Sequences**:
   - Quotes: `QT-` with 4-digit padding.
   - Sales Orders: `SO-` with 4-digit padding.
   - Invoices: `INV-` with 4-digit padding.
   - Credit Notes: `CN-` with 4-digit padding.

## Consequences
- Clean separation of business layers: `apps.sales` coordinates `apps.catalog`, `apps.inventory`, `apps.accounting`, and `apps.customers`.
- Guaranteed auditability and mathematical integrity: debits == credits, stock ledger cost == COGS journal lines, customer balance == AR journal line.
- Lays the foundation for POS checkout (P2-06) and Customer Payments (P2-05).
