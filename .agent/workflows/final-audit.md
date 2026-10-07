---
description: Final completeness audit and handoff package for the human evaluator.
---
# /final-audit
1. Every backlog item `[x]`; `docs/BLOCKERS.md` reviewed (each entry has a working fake/adapter and a note).
2. `make verify` + `/verify` green from a clean database: drop/recreate dev db, `migrate`, `seed_demo`, run all tests.
3. End-to-end story test (`tests/e2e/test_business_story.py`) passes: register org -> configure branch/warehouse -> invite user ->
   create products -> purchase & receive -> sell via POS and invoice -> collect payment -> expense -> payroll run -> dashboard figures
   and reports reconcile to ledgers -> webhook delivered -> API key call -> automation rule fires -> AI assistant answers a question
   with tool-grounded data.
4. Run `/visual-qa` for every module's screens; fix visual/UX defects against `docs/design/design-system.md`.
5. Security pass: run tenant isolation suite, `check --deploy`, dependency audit (`pip-audit`), review `docs/BLOCKERS.md`.
6. Write `docs/EVALUATION.md`: how to run (3 commands), seeded demo orgs + logins, module-by-module feature list, API docs URL,
   known limitations, architecture decision list. Commit `chore: final audit`.
