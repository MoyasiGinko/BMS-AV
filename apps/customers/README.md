# Customers Module (`apps.customers`)

Customer relationship primitives, contact addresses, credit limit enforcement, and accounts receivable balance tracking.

## Responsibilities
- **Customer Master Data**: `Customer`, `CustomerAddress`, `CustomerContact`.
- **Credit Limit & AR Controls**: Tracks `credit_limit`, `current_balance`, and `payment_terms_days`. Pre-checkout and pre-order credit checks reject orders exceeding credit bounds.
- **Transactional Services**:
  - `create_customer`, `update_customer`, `archive_customer`
  - `add_customer_address`, `add_customer_contact`
  - `adjust_customer_balance`: Atomic updates with row-level locks.
- **Domain Events**: Publishes `customers.customer_created`, `customers.customer_updated`, `customers.balance_changed`.
- **Interfaces**:
  - Full HTMX UI: customer directory, detailed customer overview (balance summary, addresses, order history), modal forms.
  - REST API v1 (`/api/v1/customers/`): filterable by search term and status, OpenAPI documented.
- **Permissions**: Three-layer security (`customers` plan entitlement, `customers.view_customer` / `manage_customer` roles, tenant isolation).
