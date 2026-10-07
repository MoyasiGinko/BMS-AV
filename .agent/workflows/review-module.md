---
description: Self-review of a finished module against the architecture, security, accounting and design rules, with fixes applied.
---
# /review-module <app>
Checklist, fix every miss immediately, then commit `review(<app>): ...`:
- [ ] All writes in `services.py` (atomic, locked, event published); views/serializers/tasks only call services.
- [ ] Models: `TenantModel`, org-leading uniques/indexes, `public_id`, Decimal fields, `Meta.constraints`, `__str__`, RLS enabled.
- [ ] Permissions: entitlement + role + scope on web, API and tasks; negative tests exist.
- [ ] Cross-tenant tests exist for list/detail/update/delete/export.
- [ ] Ledger/stock effects match `.agent/rules/30-accounting-inventory.md`; invariants tested.
- [ ] API: versioned, paginated, filterable, idempotent where needed, in OpenAPI, error format correct.
- [ ] UI: uses component library; list/detail/form screens complete with empty/loading/error states; keyboard + mobile ok.
- [ ] No N+1 (query-count tests), no TODO/pass/NotImplemented, no dead code, i18n strings wrapped.
- [ ] Docs: module README (purpose, models, services, events, permissions) updated.
