---
description: Systematic procedure to turn a red gate green without weakening it.
---
# /fix-failures
1. Re-run the failing step alone to get the full error. Read it completely.
2. Classify: (a) real bug in code -> fix code; (b) wrong/outdated test -> fix the test only if the spec in `docs/` says the test is wrong,
   and note why in the commit; (c) architecture violation -> restructure (move code down a layer or use an event); (d) environment ->
   repair environment; (e) migration drift -> `python manage.py makemigrations` and review the file.
3. Fix root cause. Never silence (`noqa`, `type: ignore`, skip, xfail, loosened assertions, lowered coverage).
4. Re-run the single step, then the full `make verify`.
5. Attempt counter: after 3 failed attempts change approach; after 5 log to `docs/BLOCKERS.md`, mark task `[!]`, move on.
