# ADR 0004: Add billing.PlanModule to Architecture Global Allowlist
Status: accepted | Date: 2026-10-07
Context: Architecture test `test_every_business_model_is_tenant_scoped` validates that every non-allowlisted business model inherits TenantModel.
Decision: Add `billing.PlanModule` to `GLOBAL_ALLOWLIST` in `tests/architecture/test_tenancy_audit.py`. `PlanModule` links global operator tiers (`billing.Plan`) and system feature specifications (`billing.Module`), neither of which is tenant-owned.
Consequences: Tenant models (`billing.Subscription`, `billing.UsageCounter`) remain strictly tenant-scoped under TenantModel and PostgreSQL RLS. Global platform catalog models (`Plan`, `Module`, `PlanModule`) remain global.
