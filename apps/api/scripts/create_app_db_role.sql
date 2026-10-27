-- Least-privilege application database role (Phase 5: tenant isolation).
--
-- WHY: Row Level Security is NOT enforced for superusers or for roles with BYPASSRLS
-- (FORCE ROW LEVEL SECURITY only covers the table owner). If the API/worker connect as the
-- owner/superuser (the docker-compose `dev` user is a superuser), every tenant policy in
-- alembic/versions is silently bypassed. Run the app as this NOBYPASSRLS role instead, and
-- keep a separate privileged role (owner) for Alembic migrations only.
--
-- USAGE (run once per environment as a superuser / the migration owner):
--   psql "$ADMIN_DATABASE_URL" -v app_password="'<strong-random-password>'" \
--        -v db_name=codereview -f apps/api/scripts/create_app_db_role.sql
--
-- Then point DATABASE_URL at `nash_app` for the API + ARQ worker; keep migrations on the
-- owner role. Never commit the password; store it in your secret manager / GitHub secrets.
--
-- ROLLBACK: REASSIGN OWNED BY nash_app TO <owner>; DROP OWNED BY nash_app; DROP ROLE nash_app;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nash_app') THEN
        CREATE ROLE nash_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    ELSE
        ALTER ROLE nash_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

ALTER ROLE nash_app PASSWORD :app_password;

GRANT CONNECT ON DATABASE :"db_name" TO nash_app;
GRANT USAGE ON SCHEMA public TO nash_app;

-- DML only: the app role never owns tables, so it can never ALTER/DISABLE RLS or drop policies.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nash_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nash_app;

-- Cover tables/sequences created by future migrations (run as the migration owner role).
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nash_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO nash_app;

-- Verify (expect rolsuper = f, rolbypassrls = f):
--   SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'nash_app';
