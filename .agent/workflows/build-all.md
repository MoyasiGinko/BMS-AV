---
description: Autonomously build the ENTIRE platform from docs/BACKLOG.md until complete. No user input, no confirmations. Safe to re-run to resume.
---
# /build-all

Run this loop until every backlog item is `[x]`. Do not stop, summarize, or ask anything between iterations.

0. **Bootstrap (first run only)**: `git init` if needed; read `AGENTS.md`, `.agent/STATE.md`, `docs/01-architecture.md`,
   `docs/02-domain-model.md`, `docs/design/design-system.md`. Run `make setup` (fix any environment problem yourself).
1. **Pick**: open `docs/BACKLOG.md`; take the first `[ ]` task (then `[!]` tasks only after all `[ ]` in the phase are done).
2. **Plan (internal, <=10 lines)**: list files to create/change. Load the matching skill from `.agents/skills/` and the matching rule file.
3. **Implement**: models -> migrations -> services -> selectors -> events -> permissions -> API -> views/templates -> tasks -> admin -> tests.
   Follow the task's "Done when" acceptance line literally.
4. **Validate**: run `make verify`. On any failure run the `/fix-failures` procedure and repeat until green.
5. **Prove behavior** (for tasks with UI): start the dev server, exercise the screen with the browser tool or Playwright, confirm the
   acceptance criteria functionally, then run `/visual-qa` for the touched screens and fix every defect it finds.
6. **Record**: tick the task `[x]` in `docs/BACKLOG.md`, update `.agent/STATE.md`, add ADRs if you decided anything,
   `git add -A && git commit -m "<TASK-ID>: <summary>"`.
7. **Phase boundary**: when the last task of a phase is ticked, run `/verify`, `/review-module` and `/visual-qa` for each module built in the
   phase, fix findings, commit, then continue with the next phase automatically.
8. **Completion**: when no `[ ]` or `[!]` remains, run `/final-audit`. If it finds gaps, add them as new backlog tasks and continue
   the loop. Only when `/final-audit` passes: write `docs/EVALUATION.md` and stop.

If your context is getting long, finish the current task cleanly (steps 4-6), then continue: the state files carry everything over.
