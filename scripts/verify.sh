#!/usr/bin/env bash
# THE quality gate. Do not edit without an ADR. Exit non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.test}"
step() { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }

step "ruff lint";            ruff check .
step "ruff format";          ruff format --check .
step "mypy";                 mypy apps config
step "migrations in sync";   python manage.py makemigrations --check --dry-run
step "django check";         python manage.py check
step "import contracts";     lint-imports
step "tests + coverage";     pytest -q --cov=apps --cov-report=term-missing:skip-covered --cov-fail-under="${COV_MIN:-80}"
step "openapi schema";       python manage.py spectacular --file /tmp/schema.yml --validate --fail-on-warn
step "deploy check";         DJANGO_SETTINGS_MODULE=config.settings.prod_check python manage.py check --deploy --fail-level WARNING
printf '\n\033[1;32mVERIFY PASSED\033[0m\n'
