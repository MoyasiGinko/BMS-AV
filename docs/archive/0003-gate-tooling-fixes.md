# ADR 0003: Tooling fixes required to make the kit's gate runnable
Status: accepted | Date: 2026-10-07
Context: With current tool versions the untouched kit fails its own gate: ruff 0.16 lints/formats Markdown code fences in `.agent(s)/` and `docs/`
(illustrative pseudo-code, e.g. `{...}`), the kit's `tests/architecture/*.py` violate PLC0415/E501/I001 and are unformatted, and `celery`/`environ`
ship no type information so mypy reports `import-untyped`.
Decision: (1) add `.agent`, `.agents`, `docs` to ruff `extend-exclude` (documentation, not code); (2) lint/format-only edits to `tests/architecture/*.py`
(imports moved to module top, which pytest-django supports because Django is set up before collection; long lines wrapped) with zero assertion changes;
(3) a mypy override `ignore_missing_imports` limited to named untyped third-party packages. No rule was disabled for project code.
Consequences: Gate strength on `apps/`, `config/`, `tests/` is unchanged; new untyped libraries must be added to the named list explicitly.
