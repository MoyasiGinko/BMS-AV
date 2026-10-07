# Business OS: Antigravity Autonomous Build Kit

Drop this folder's contents into an empty repository and let Antigravity build the platform end to end.

## 1. One-time setup (about 10 minutes)
1. Install: **Python 3.14**, **uv** (`pip install uv` or see docs.astral.sh/uv), Git, Docker Desktop (or local PostgreSQL 18 + Redis 8). Node is NOT needed (only for the optional Context7 MCP). Playwright browsers are installed by the agent.
2. Create a new folder, copy the entire kit into it (keep the hidden `.agent/` and `.agents/` folders), run `git init`.
3. Open that folder as a workspace in Antigravity.
4. **Agent autonomy settings** (Antigravity Settings -> Agent / Advanced; labels may differ slightly by version):
   - Terminal execution policy: **Always proceed** (Turbo / Auto)
   - Review policy: **Always proceed** (never asks for feedback)
   - JavaScript / browser execution policy: **Always proceed**
   - Terminal **deny list** (keep these blocked so unattended runs cannot hurt your machine): `rm -rf /`, `rm -rf ~`, `sudo`, `git push --force`,
     `mkfs`, `dd if=`, `shutdown`, `reboot`, `curl ... | sh`.
   - Allow list: python, pip, pytest, ruff, mypy, lint-imports, make, git, docker, docker compose, psql, redis-cli, celery, playwright, rg, tailwindcss.
5. Model: pick the strongest model available (e.g. highest-tier Gemini Pro / Claude option) with the longest context. Plan mode off; fast/agent mode on.
6. Make sure the machine will not sleep (power settings) and Antigravity stays open.

### Optional MCP (recommended: Context7 only)
Context7 gives the agent live library docs (Django, DRF, HTMX, Tailwind...). Requires Node.js. In Antigravity open the agent panel -> `...` ->
MCP Servers -> Manage MCP Servers -> View raw config, and merge the contents of `mcp_config.example.json`. No other MCP is needed for design:
the built-in browser plus `/visual-qa` handles it. Skip Figma unless you already have Figma designs.

### Optional: your own visual references
Drop screenshots of UIs you like into `docs/design/reference/`. The agent matches them in `/visual-qa`.

## 2. Start the build
In the Agent Manager (or Cmd/Ctrl+L panel) paste:

> Run /build-all. Do not ask me anything. Work until the entire docs/BACKLOG.md is complete and /final-audit passes.

(Or just type `/build-all`.) The agent then loops: pick task -> implement -> `make verify` -> fix -> commit -> next, for all ~70 tasks.

## 3. If it stops
Agents can still halt because of model quota, rate limits, context exhaustion, or an app update. The kit is built for that: all progress is in
`docs/BACKLOG.md`, `.agent/STATE.md` and git commits. Just open a new conversation and run `/build-all` again. It resumes at the next unticked task.
Check `git log --oneline` to see progress.

## 4. What keeps it honest (auto-validation)
- `make verify` is the gate: ruff, formatting, mypy, migration drift, `manage.py check`, **import-linter architecture contracts**,
  tests + 80% coverage, OpenAPI validation, `check --deploy`.
- `tests/architecture/` fails the build if any model is not tenant-scoped, uses floats for money, has non-org-scoped uniques, or an API view is unprotected.
- Rules forbid weakening tests/gates, stubbing real features, or asking you for input; failures follow a fix-or-log protocol (`docs/BLOCKERS.md`).
- Phase reviews (`/review-module`), `/verify` (adds Playwright UI smoke + invariants), and `/final-audit` (end-to-end business story).

## 5. When it finishes: your evaluation
Read `docs/EVALUATION.md` (written by the agent). Typical commands:
```
make setup && make seed && make run     # http://localhost:8000  (demo logins in EVALUATION.md)
make verify                             # re-run the whole gate yourself
```
Also review `docs/adr/` (decisions the agent made for you) and `docs/BLOCKERS.md` (fakes/stubs used for external services).

## Kit contents
```
AGENTS.md / GEMINI.md          always-loaded operating manual (autonomy contract, hard rules)
.agent/rules/*.md              7 rules (2 always-on, 5 loaded when relevant)
.agent/workflows/*.md          /build-all  /verify  /visual-qa  /fix-failures  /review-module  /final-audit
.agent/STATE.md                resumable progress state
.agents/skills/*/SKILL.md      6 skills: module scaffold, ledger posting, DRF endpoint, HTMX screen, tenant-isolation tests, events/webhooks
docs/00..04-*.md, STACK.md     product story, architecture, domain model, API/integrations, testing spec, pinned latest tech stack
docs/BACKLOG.md                ~75 ordered tasks with acceptance criteria (P0 foundations ... P7 delivery)
docs/design/                   design system, tokens, visual reference mockup (open reference-screens.html)
static/css/tokens.css, input.css   design tokens + Tailwind 4 theme mapping
scripts/verify.sh, Makefile, pyproject.toml  the quality gate and tooling config
tests/architecture/            tenancy, money, constraint and API protection audits
.github/workflows/ci.yml, docker-compose.yml, .env.example
```

## Honest limits
- Exact setting names/locations in Antigravity change between releases; the intent is "never ask, never block, always run commands".
- A project this size is many hours of agent work and a lot of model quota. Expect to re-run `/build-all` a few times.
- Optional: export the full development guideline document as Markdown and save it as `docs/reference/full-guideline.md`; the agent treats it as extra context.
