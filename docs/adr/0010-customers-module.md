# 0010. Customer Subledger, Addresses, Statements, and Credit Control

Date: 2026-10-08

## Context
Phase P2 requires comprehensive customer relationship and financial tracking:
1. Customer identity, classification (individual/business), tax registration, currency, and assigned price list.
2. Multiple structured addresses (billing, shipping) and multiple organizational contacts with primary designation.
3. An immutable financial subledger (`CustomerBalanceEntry`) recording all AR movements (invoices, payments, credit notes, refunds, adjustments) ensuring the customer's balance always matches the sum of transactions.
4. Customer account statements with period opening balance, transaction ledger, closing balance, and aged receivable analysis.
5. Strict credit limit checks preventing orders/invoices when the customer exceeds approved credit terms.
6. Multi-tenant scoping, HTMX UI screens, and a versioned REST API under `/api/v1/customers/`.

## Decision
1. **Domain Models**:
   - `Customer`: Scoped by `organization`, code (e.g. `CUST-0001`), name, type (`INDIVIDUAL`, `BUSINESS`), tax ID, currency, credit limit, payment terms (days), price list (FK to `catalog.PriceList`), notes, status (`ACTIVE`, `INACTIVE`, `SUSPENDED`), and cached `current_balance`.
   - `CustomerAddress`: Addresses categorized as `BILLING`, `SHIPPING`, or `OTHER`, with `is_default` handling.
   - `CustomerContact`: First/last name, email, phone, role/title, and `is_primary` flag.
   - `CustomerBalanceEntry`: Immutable subledger records with `entry_type` (`INVOICE`, `PAYMENT`, `CREDIT_NOTE`, `REFUND`, `ADJUSTMENT`), `debit`, `credit`, `balance_after`, `reference_type/id/number`, `occurred_at`, and `description`.
2. **Subledger & Concurrency**:
   - All balance updates (`post_customer_transaction`, `record_customer_charge`, `record_customer_credit`) acquire a `select_for_update` row lock on `Customer` inside `@transaction.atomic`.
   - Current balance is strictly computed as `current_balance + debit - credit` and saved on the customer record alongside the immutable ledger entry.
3. **Credit Limit Control**:
   - `check_credit_limit` inspects `credit_limit`. If set (> 0) and `current_balance + additional_amount > credit_limit`, it returns false or raises `CreditLimitExceeded`. Suspended customers are blocked from new charges.
4. **Statements & Aging**:
   - `get_customer_statement` computes opening balance prior to the start date, extracts all ledger lines within the date range, and evaluates aged receivable buckets: Current, 1-30 days, 31-60 days, 61-90 days, 90+ days.
5. **UI & API**:
   - Server-rendered screens with HTMX filtering, tabbed detail views (Transactions, Statements, Addresses, Contacts), and REST API endpoints at `/api/v1/customers/` and `/api/v1/customers/entries/`.

## Consequences
- Guaranteed auditability and mathematical integrity between customer balance and financial records.
- Ready for sales order confirmation and invoice posting in P2-04.
