---
trigger: always_on
---
# Testing & Validation Rules (always on)

- Definition of done for ANY task: code + tests + `make verify` green + docs/ADR updated if a decision was made + backlog ticked + commit.
- Test pyramid: unit (services, calculators, state machines) -> integration (full flows across modules) -> API contract ->
  tenant isolation -> accounting/stock invariants (hypothesis) -> UI smoke (Playwright).
- Each service test set covers: success, permission denied, plan not entitled, cross-tenant access, validation failure, rollback on error.
- Use factory_boy factories in `tests/factories/`; each test creates its own organization. No shared mutable fixtures.
- Query-count assertions on list endpoints and dashboards (no N+1).
- After finishing a PHASE run `/verify` (full gate + smoke + invariants) and the `/review-module` workflow for each module of the phase.
- Before declaring the project complete run `/final-audit`.
