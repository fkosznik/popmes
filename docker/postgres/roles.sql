-- Migration owner and DML-only application role.
-- Invoke with psql variables app_user, migrate_user, app_db, app_password, migrate_password.
-- This file is not executed on its own.

SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'migrate_user', :'migrate_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrate_user') \gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'migrate_user', :'migrate_password'
) \gexec

SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'app_user', :'app_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'app_user', :'app_password'
) \gexec

SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I, %I',
    :'app_db', :'migrate_user', :'app_user'
) \gexec

GRANT USAGE, CREATE ON SCHEMA public TO :"migrate_user";
GRANT USAGE ON SCHEMA public TO :"app_user";

SELECT set_config('popmes.migrate_user', :'migrate_user', false);
SELECT set_config('popmes.app_user', :'app_user', false);

DO $$
DECLARE
    migrate_name text := current_setting('popmes.migrate_user');
    app_name text := current_setting('popmes.app_user');
    row record;
BEGIN
    FOR row IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO %I', row.tablename, migrate_name);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I',
            row.tablename, app_name
        );
    END LOOP;
    FOR row IN
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'public'
    LOOP
        EXECUTE format(
            'ALTER SEQUENCE public.%I OWNER TO %I',
            row.sequence_name, migrate_name
        );
        EXECUTE format(
            'GRANT USAGE, SELECT ON SEQUENCE public.%I TO %I',
            row.sequence_name, app_name
        );
    END LOOP;
    EXECUTE format('ALTER SCHEMA public OWNER TO %I', migrate_name);
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
        migrate_name, app_name
    );
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO %I',
        migrate_name, app_name
    );
END
$$;
