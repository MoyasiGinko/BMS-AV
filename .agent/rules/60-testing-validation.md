---
trigger: always_on
---
# Testing & Validation Rules (always on)

- Tiered definition of done:
  * Core backend / services / accounting / data tasks: code + tests + `make verify` green + docs/ADR updated if a decision was made + backlog ticked + commit. Invariants and full test suites are non-negotiable.
  * Frontend / UI / template / styling tasks: clean code adhering to design system + 1-shot visual inspection (confirming tactile, high-contrast, zero-border neumorphic quality) + linter check (`djlint`/`ruff`). Do NOT boot slow backend database test suites (`pytest`) or loop on auxiliary test runners for pure visual/styling changes. Keep turnarounds fast (<30s).
- Test pyramid: unit (services, calculators, state machines) -> integration (full flows across modules) -> API contract ->
  tenant isolation -> accounting/stock invariants (hypothesis) -> UI smoke (Playwright).
- Each service test set covers: success, permission denied, plan not entitled, cross-tenant access, validation failure, rollback on error.
- Use factory_boy factories in `tests/factories/`; each test creates its own organization. No shared mutable fixtures.
- Query-count assertions on list endpoints and dashboards (no N+1).
- After finishing a PHASE run `/verify` (full gate + smoke + invariants) and the `/review-module` workflow for each module of the phase.
- Before declaring the project complete run `/final-audit`.
