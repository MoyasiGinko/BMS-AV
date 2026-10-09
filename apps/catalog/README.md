# Catalog Module (`apps.catalog`)

Product catalog, item categorization, pricing, units of measure, and tax configuration for Business OS.

## Responsibilities
- **Product Hierarchy & Master Data**: `Category`, `Unit`, `Product` (stock, service, and composite bundles).
- **Pricing & Multi-Currency Ready**: Selling prices, cost prices, standard markup calculations, and decimal precision (`Decimal(18, 4)`).
- **Tax Classification**: Mapping products to tenant-defined `TaxCode` records (`VAT10`, `ZERO`, etc.).
- **Multi-Tenant Scoping**: All models inherit `TenantModel` with row-level security (`app.current_org`) and tenant-leading indexes (`organization_id`, `sku`).
- **Transactional Services**:
  - `create_product`, `update_product`, `archive_product`
  - `create_category`, `update_category`
  - `create_unit`
- **Domain Events**: Publishes `catalog.product_created`, `catalog.product_updated`, `catalog.product_archived` via transactional outbox.
- **Interfaces**:
  - Full HTMX UI: product list, create/edit modals, category filtering, search, pagination.
  - REST API v1 (`/api/v1/catalog/products/`): paginated, searchable, OpenAPI documented.
- **Permissions**: Entitlement checks (`catalog` module active), role permissions (`catalog.view_product`, `catalog.manage_product`), and organization scoping.
