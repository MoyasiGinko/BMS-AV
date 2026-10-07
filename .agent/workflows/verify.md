---
description: Full validation gate: lint, types, migrations, architecture contracts, tests+coverage, schema, deploy check, UI smoke, invariants.
---
# /verify
1. `make verify` (must pass).
2. `pytest -q -m ui` (Playwright smoke; start the server fixture automatically; install browsers with `playwright install chromium` if needed).
3. `pytest -q tests/architecture tests/invariants` (tenancy audit, import contracts, ledger/stock invariants).
4. `python manage.py seed_demo --reset` then hit every top-level page and every `/api/v1/` list endpoint with the test client as each
   seeded role; assert no 500s and no cross-tenant data.
5. Report failures into `docs/BLOCKERS.md` only if unfixable after the `/fix-failures` procedure; otherwise fix and re-run from 1.
