# Generated manually for RLS enforcement

from django.db import migrations

from apps.core.rls import enable_rls


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bos_app') THEN
        CREATE ROLE bos_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END $$;
GRANT ALL PRIVILEGES ON SCHEMA public TO bos_app;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bos_app;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bos_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO bos_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO bos_app;
""",
            reverse_sql="",
        ),
        enable_rls('core_numbersequence'),
    ]
