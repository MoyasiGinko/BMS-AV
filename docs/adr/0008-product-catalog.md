# ADR 0008: Product Catalog Architecture

## Context
Task P2-01 establishes the central product catalog foundation for retail, inventory, sales, purchasing, and POS.
The catalog must accommodate simple physical products, variants (size/color), non-stock services, composite bundles, hierarchical categories, multi-unit conversions, multiple tier price lists, and bulk CSV import/export.

## Decision
1. **Core Domain Entities**:
   - `Category`: Self-referencing hierarchical category tree.
   - `Unit` & `UnitConversion`: Flexible measurement units (pcs, kg, box) with conversion factors.
   - `Product`: Core commercial item with SKU, optional barcode, Category, Unit, TaxCode, cost price, selling price, and reorder levels.
   - `ProductVariant`: Variations on size, color, or other attributes with distinct SKU/barcode and optional price overrides.
   - `ProductImage`: Product media gallery with primary image flag.
   - `PriceList` & `PriceListItem`: Tiered pricing rules (Wholesale, Retail, VIP) with minimum quantity volume breaks.
2. **Decimal Precision & Clean Types**:
   - Cost and selling prices stored strictly as `DecimalField(max_digits=18, decimal_places=4)`.
   - Unit conversion factor stored as `DecimalField(max_digits=18, decimal_places=6)`.
3. **Price Resolution**:
   - `resolve_product_price(*, organization, product, variant=None, price_list=None, quantity=Decimal("1.0000"))` provides centralized price calculation factoring in price lists and volume tiers.
4. **Bulk CSV Import & Export**:
   - Streaming/buffered CSV export with headers: SKU, Barcode, Name, Category, Unit, Type, Cost Price, Selling Price, Tax Code.
   - Idempotent CSV import that matches by SKU, creates categories and units on-the-fly if needed, and updates or inserts cleanly.
5. **UI & API Integration**:
   - Server-rendered Django templates + HTMX for reactive product directory, live search, filtering, and inline updates.
   - Versioned REST API under `/api/v1/catalog/` using `TenantScopedModelViewSet` and drf-spectacular OpenAPI documentation.
6. **Row-Level Security**:
   - All catalog tenant tables enforce PostgreSQL RLS.

## Consequences
- Operational modules (Inventory, Sales, POS, Purchasing) have a clean, unified catalog abstraction.
