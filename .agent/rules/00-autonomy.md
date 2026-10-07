---
trigger: always_on
---
# Autonomy & Execution Rules (always on)

You are running unattended. There is no human to answer questions until the whole backlog is finished.

## Forbidden behaviors
- Asking "should I proceed / do you want / which do you prefer / please confirm". Never. Decide and act.
- Stopping after a task, a phase, or a summary. After finishing a task immediately start the next one.
- Ending your turn with a plan instead of doing the work. Do the work.
- Marking a task done without a passing `make verify` run in this session.
- Weakening, skipping or deleting tests/gates; blanket `# noqa`, `# type: ignore`, `pytest.skip`, `xfail` to get green.
- Stubbing real functionality with `pass`, `TODO`, `NotImplementedError` or fake data in non-test code. External systems are the only
  exception: use an adapter + a working fake and log it in `docs/BLOCKERS.md`.

## Decision protocol
1. Is it specified in `docs/`? Follow it.
2. Else choose the simplest option consistent with `docs/01-architecture.md`. Write `docs/adr/NNNN-<slug>.md` (context, decision,
   consequences, <=10 lines). Continue.

## Failure protocol
- A failing check: read the actual error, fix the root cause, rerun. Up to 5 attempts on the same failure; on the 3rd attempt change
  approach (re-read the relevant docs/skill, simplify, rewrite the unit).
- Still failing after 5: write the failure and what you tried to `docs/BLOCKERS.md`, mark the task `[!]` in the backlog, move to the
  next task, and return to `[!]` tasks at the end of the phase.
- Environment problems (db down, port busy, missing package): fix them yourself (start services, install packages, pick another
  port). Prefer docker; if docker is unavailable, install/run local PostgreSQL and Redis and write an ADR.

## Persistence (so a fresh session can resume)
After every task: tick it in `docs/BACKLOG.md`, update `.agent/STATE.md` (current phase, last task, next task, known issues), and
`git add -A && git commit -m "<task-id>: <summary>"`. Never leave the working tree dirty between tasks.

## Context hygiene
Start every task by re-reading `.agent/STATE.md` and the backlog entry. Open only the docs/skills the task needs. Do not paste
large files into the conversation; use targeted views and `rg`.

## Terminal etiquette
Run long commands with output trimmed (`| tail -n 60`) but read failures fully. Never run destructive commands outside the repo
(no `rm -rf` outside the project, no `git push --force`, no `DROP DATABASE` except the local dev/test db).
