"""PostgreSQL Row-Level Security (RLS) migration operations and helpers.

Provides defense-in-depth tenant isolation at the database engine level.
Policies enforce that queries can only access rows matching `app.current_org`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import migrations

if TYPE_CHECKING:
    from django.db.models import Model


def get_rls_sql(table_name: str) -> tuple[str, str]:
    """Return forward and reverse SQL to enable RLS and tenant policy on a table."""
    forward_sql = f"""
ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "tenant_isolation_policy" ON "{table_name}";
CREATE POLICY "tenant_isolation_policy" ON "{table_name}"
    AS PERMISSIVE
    FOR ALL
    USING (
        NULLIF(current_setting('app.current_org', true), '') IS NOT NULL
        AND organization_id = NULLIF(current_setting('app.current_org', true), '')::bigint
    )
    WITH CHECK (
        NULLIF(current_setting('app.current_org', true), '') IS NOT NULL
        AND organization_id = NULLIF(current_setting('app.current_org', true), '')::bigint
    );
DO $$ BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'bos_app') THEN
        GRANT ALL ON TABLE "{table_name}" TO bos_app;
    END IF;
END $$;
"""
    reverse_sql = f"""
DROP POLICY IF EXISTS "tenant_isolation_policy" ON "{table_name}";
ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY;
"""
    return forward_sql.strip(), reverse_sql.strip()


class EnableRLS(migrations.RunSQL):
    """Migration operation to enable Row-Level Security on a tenant table."""

    def __init__(self, model_or_table: type[Model] | str) -> None:
        if isinstance(model_or_table, str):
            self.table_name = model_or_table
        elif hasattr(model_or_table, "_meta"):
            self.table_name = model_or_table._meta.db_table
        else:
            self.table_name = str(model_or_table)

        forward_sql, reverse_sql = get_rls_sql(self.table_name)
        super().__init__(sql=forward_sql, reverse_sql=reverse_sql)

    def describe(self) -> str:
        return f"Enable Row-Level Security on {self.table_name}"


def enable_rls(model_or_table: type[Model] | str) -> EnableRLS:
    """Helper for migration operations to enable RLS on a tenant model or table."""
    return EnableRLS(model_or_table)


def ensure_app_role(connection: Any) -> str:
    """Ensure non-superuser role (bos_app) exists with proper schema permissions."""
    role_name = "bos_app"
    with connection.cursor() as cursor:
        cursor.execute(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role_name}') THEN
                    CREATE ROLE {role_name} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END $$;
            GRANT ALL PRIVILEGES ON SCHEMA public TO {role_name};
            GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {role_name};
            GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {role_name};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {role_name};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {role_name};
        """)
    return role_name
