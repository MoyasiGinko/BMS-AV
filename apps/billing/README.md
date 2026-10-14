# Billing Module (`apps.billing`)

SaaS subscription lifecycle, plan tiers, entitlement enforcement, feature gates, usage metering, and invoice generation.

## Architecture & Responsibilities
- **Domain Models**:
  - `Plan`: Platform subscription tier (e.g., `Starter`, `Growth`, `Business`, `Enterprise`) defining monthly/yearly pricing, currencies, trial durations, and resource quotas (`max_users`, `max_branches`, `max_warehouses`).
  - `Module`: System functional modules (e.g., `catalog`, `inventory`, `sales`, `accounting`, `pos`, `crm`, `hr`, `payroll`, `reports`, `automation`, `ai_assistant`, `integrations`).
  - `PlanModule`: Many-to-many relationship mapping which system modules and feature flags are entitled per plan tier.
  - `Subscription`: Organization-scoped subscription status (`TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELED`, `UNPAID`), billing cycles (`MONTHLY`, `YEARLY`), payment provider reference IDs, and renewal dates.
  - `UsageCounter`: Organization-scoped operational metrics tracking resource utilization against plan quotas (e.g., active user count, API requests, invoices generated).
- **Entitlement Enforcement**:
  - `check_entitlement(organization, module_key)` selector validating whether the tenant's active subscription tier permits access to a specific functional capability.
  - View decorators, DRF permission classes (`HasPlanEntitlement`), and HTMX UI conditional badges guarding premium functionality.
- **Payment Gateway Abstraction**:
  - Pluggable payment provider adapter pattern (`BillingGatewayAdapter`).
  - Native support for sandbox/mock payment provider (`MockBillingAdapter`) for offline testing and deterministic verification.
  - Outbound subscription renewal processing and webhook listeners for customer charge events.
- **Interfaces**:
  - Subscription management screens (`/billing/`): current plan overview, feature comparison matrix, upgrade/downgrade modals, and invoice download history.
  - REST API v1 (`/api/v1/billing/plans/`, `/subscriptions/`, `/usage/`).
