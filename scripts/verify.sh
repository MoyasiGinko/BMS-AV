#!/usr/bin/env bash
# THE quality gate. Do not edit without an ADR. Exit non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.test}"
RUN=""; command -v uv >/dev/null 2>&1 && RUN="uv run"
step() { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }

step "ruff lint";            $RUN ruff check .
step "ruff format";          $RUN ruff format --check .
step "mypy";                 $RUN mypy apps config
step "migrations in sync";   $RUN python manage.py makemigrations --check --dry-run
step "django check";         $RUN python manage.py check
step "import contracts";     $RUN lint-imports
step "tests + coverage";     $RUN pytest -q --cov=apps --cov-report=term-missing:skip-covered --cov-fail-under="${COV_MIN:-80}"
step "openapi schema";       $RUN python manage.py spectacular --file /tmp/schema.yml --validate --fail-on-warn
step "deploy check";         DJANGO_SETTINGS_MODULE=config.settings.prod_check $RUN python manage.py check --deploy --fail-level WARNING
step "dependency health";    $RUN pip check
printf '\n\033[1;32mVERIFY PASSED\033[0m\n'
