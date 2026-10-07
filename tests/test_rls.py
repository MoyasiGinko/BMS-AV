"""Tests for PostgreSQL Row-Level Security (RLS) enforcement and raw SQL tenant isolation."""

from __future__ import annotations

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError, ProgrammingError

from apps.accounts.models import User
from apps.core.models import TenantModel
from apps.core.rls import enable_rls, ensure_app_role, get_rls_sql
from apps.core.tenant_context import (
    get_current_organization_id,
    tenant_context,
)
from apps.tenancy.models import Branch, Organization
from tests.architecture.test_tenancy_audit import _business_models


@pytest.mark.django_db
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
def test_every_tenant_model_has_rls_enabled_in_postgres() -> None:
    """Verify in PostgreSQL catalog that all TenantModel tables have RLS and policies enabled."""
    if connection.vendor != "postgresql":
        pytest.skip("RLS catalog inspection requires PostgreSQL")

    with connection.cursor() as cursor:
        for model in _business_models():
            if not issubclass(model, TenantModel):
                continue

            table = model._meta.db_table
            # 1. Check relrowsecurity and relforcerowsecurity on pg_class
            cursor.execute(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = %s;
                """,
                [table],
            )
            row = cursor.fetchone()
            assert row is not None, f"Table {table} not found in public schema"
            has_rls, force_rls = row
            assert has_rls is True, f"Table {table} does not have ROW LEVEL SECURITY enabled"
            assert force_rls is True, f"Table {table} does not have FORCE ROW LEVEL SECURITY enabled"

            # 2. Check policy exists in pg_policy
            cursor.execute(
                """
                SELECT polname
                FROM pg_policy pol
                JOIN pg_class c ON c.oid = pol.polrelid
                WHERE c.relname = %s AND pol.polname = 'tenant_isolation_policy';
                """,
                [table],
            )
            pol = cursor.fetchone()
            assert pol is not None, f"Table {table} is missing 'tenant_isolation_policy'"


@pytest.mark.django_db
def test_raw_sql_cross_org_reads_return_nothing() -> None:
    """Prove that raw SQL queries under a non-superuser role return nothing for other orgs."""
    if connection.vendor != "postgresql":
        pytest.skip("RLS testing requires PostgreSQL")

    ensure_app_role(connection)

    # Setup: create two organizations and branches
    _ = User.objects.create_user(email="rls_tester@example.com", password="PassWord123!")
    org_a = Organization.objects.create(name="Tenant Alpha", slug="tenant-alpha")
    org_b = Organization.objects.create(name="Tenant Beta", slug="tenant-beta")

    branch_a = Branch.all_tenants.create(
        organization=org_a,
        name="Alpha Headquarters",
        code="ALPHA-HQ",
        is_headquarters=True,
    )
    branch_b = Branch.all_tenants.create(
        organization=org_b,
        name="Beta Branch",
        code="BETA-BR",
        is_headquarters=True,
    )

    with connection.cursor() as cursor:
        # Switch to application role to enforce RLS
        cursor.execute("SET ROLE bos_app;")
        try:
            # 1. No tenant context set -> raw SQL read returns nothing
            cursor.execute("SELECT id, name FROM tenancy_branch;")
            rows_no_ctx = cursor.fetchall()
            assert rows_no_ctx == [], f"Expected empty list when no tenant context, got {rows_no_ctx}"

            # 2. Activate Org A -> raw SQL returns only Org A's branch
            with tenant_context(org_a):
                cursor.execute("SELECT id, name FROM tenancy_branch;")
                rows_a = cursor.fetchall()
                assert len(rows_a) == 1
                assert rows_a[0][0] == branch_a.id
                assert rows_a[0][1] == "Alpha Headquarters"

                # Direct cross-org filter query returns nothing
                cursor.execute(
                    "SELECT id, name FROM tenancy_branch WHERE organization_id = %s;",
                    [org_b.id],
                )
                cross_read = cursor.fetchall()
                assert cross_read == [], "Cross-org raw SQL read must return nothing"

            # 3. Activate Org B -> raw SQL returns only Org B's branch
            with tenant_context(org_b):
                cursor.execute("SELECT id, name FROM tenancy_branch;")
                rows_b = cursor.fetchall()
                assert len(rows_b) == 1
                assert rows_b[0][0] == branch_b.id
                assert rows_b[0][1] == "Beta Branch"

                # Direct cross-org filter query returns nothing
                cursor.execute(
                    "SELECT id, name FROM tenancy_branch WHERE organization_id = %s;",
                    [org_a.id],
                )
                cross_read = cursor.fetchall()
                assert cross_read == [], "Cross-org raw SQL read must return nothing"

            # 4. Context exited -> raw SQL reads return nothing again
            cursor.execute("SELECT id, name FROM tenancy_branch;")
            assert cursor.fetchall() == []

        finally:
            cursor.execute("RESET ROLE;")


@pytest.mark.django_db
def test_raw_sql_cross_org_insert_violates_policy() -> None:
    """Verify that attempting to insert a row for Org B while Org A context is active fails RLS check."""
    if connection.vendor != "postgresql":
        pytest.skip("RLS testing requires PostgreSQL")

    ensure_app_role(connection)

    org_a = Organization.objects.create(name="Tenant Insert A", slug="tenant-insert-a")
    org_b = Organization.objects.create(name="Tenant Insert B", slug="tenant-insert-b")

    with connection.cursor() as cursor:
        cursor.execute("SET ROLE bos_app;")
        try:
            with (
                tenant_context(org_a),
                pytest.raises((IntegrityError, ProgrammingError)) as exc_info,
                transaction.atomic(),
            ):
                cursor.execute(
                    """
                    INSERT INTO tenancy_branch (
                        public_id, organization_id, name, code,
                        is_headquarters, is_active, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), %s, 'Illicit Branch', 'ILLICIT', false, true, NOW(), NOW()
                    );
                    """,
                    [org_b.id],
                )
                assert "row-level security" in str(exc_info.value).lower()
        finally:
            cursor.execute("RESET ROLE;")


@pytest.mark.django_db
def test_tenant_context_nested_and_reset() -> None:
    """Test tenant_context correctly sets and restores session app.current_org."""
    if connection.vendor != "postgresql":
        pytest.skip("RLS testing requires PostgreSQL")

    org_1 = Organization.objects.create(name="Org One", slug="org-one")
    org_2 = Organization.objects.create(name="Org Two", slug="org-two")

    def _get_setting() -> str:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.current_org', true);")
            row = cursor.fetchone()
            return row[0] if row else ""

    assert _get_setting() in ("", None)
    assert get_current_organization_id() is None

    with tenant_context(org_1):
        assert get_current_organization_id() == org_1.id
        assert _get_setting() == str(org_1.id)

        with tenant_context(org_2):
            assert get_current_organization_id() == org_2.id
            assert _get_setting() == str(org_2.id)

        # Restored to org_1
        assert get_current_organization_id() == org_1.id
        assert _get_setting() == str(org_1.id)

    # Restored to None / empty
    assert get_current_organization_id() is None
    assert _get_setting() in ("", None)
