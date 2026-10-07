"""Core-level unit tests for RLS SQL generator and context variables (no higher layer imports)."""

from __future__ import annotations

import pytest
from django.db import connection

from apps.core.rls import enable_rls, ensure_app_role, get_rls_sql
from apps.core.tenant_context import (
    get_current_organization_id,
    set_current_organization,
    tenant_context,
)


def test_enable_rls_helper_generates_valid_sql() -> None:
    """Verify get_rls_sql and enable_rls helper create valid SQL structures."""
    fwd, rev = get_rls_sql("sample_tenant_table")
    assert 'ALTER TABLE "sample_tenant_table" ENABLE ROW LEVEL SECURITY;' in fwd
    assert 'ALTER TABLE "sample_tenant_table" FORCE ROW LEVEL SECURITY;' in fwd
    assert 'CREATE POLICY "tenant_isolation_policy" ON "sample_tenant_table"' in fwd
    assert 'ALTER TABLE "sample_tenant_table" DISABLE ROW LEVEL SECURITY;' in rev

    op = enable_rls("sample_tenant_table")
    assert op.table_name == "sample_tenant_table"
    assert "Row-Level Security" in op.describe()


@pytest.mark.django_db
def test_ensure_app_role_executes() -> None:
    """Verify ensure_app_role successfully creates or confirms the bos_app role."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL required")

    role_name = ensure_app_role(connection)
    assert role_name == "bos_app"


@pytest.mark.django_db
def test_tenant_context_numeric_id() -> None:
    """Test tenant_context operates cleanly with numeric organization IDs."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL required")

    def _get_setting() -> str:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.current_org', true);")
            row = cursor.fetchone()
            return row[0] if row else ""

    assert get_current_organization_id() is None
    with tenant_context(42):
        assert get_current_organization_id() == 42
        assert _get_setting() == "42"

        with tenant_context(99):
            assert get_current_organization_id() == 99
            assert _get_setting() == "99"

        assert get_current_organization_id() == 42
        assert _get_setting() == "42"

    assert get_current_organization_id() is None
    assert _get_setting() in ("", None)


@pytest.mark.django_db
def test_set_current_organization_numeric() -> None:
    """Test set_current_organization with integer IDs."""
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL required")

    set_current_organization(77)
    assert get_current_organization_id() == 77

    set_current_organization(None)
    assert get_current_organization_id() is None
