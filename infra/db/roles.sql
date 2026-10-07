-- hospital-sys database roles: create or repair them and their privileges. Idempotent.
--
--   owner  owns the database and every object in schema public. Only migrations connect as
--          it (the compose `migrate` service, infra/update.sh, the first install).
--   app    what the application connects as: LOGIN, nothing else. SELECT/INSERT/UPDATE/DELETE
--          on tables, USAGE/SELECT on sequences, EXECUTE on functions. It owns nothing and is
--          a member of no role, so it cannot TRUNCATE, ALTER, DROP or disable the protection
--          triggers (ADR 0006), and it cannot create objects.
--
-- Run by infra/db/roles.sh (never directly) as a superuser connected to the target database.
-- The wrapper sets: owner_role, app_role, set_passwords (true/false), owner_pw, app_pw.
-- One transaction: a failure leaves roles, ownership and grants exactly as they were.

\set ON_ERROR_STOP on
SET client_min_messages = warning;

BEGIN;
-- Never write the role passwords to the server log, whatever its logging settings.
SET LOCAL log_statement = 'none';
SET LOCAL log_min_duration_statement = -1;
SET LOCAL log_min_error_statement = 'panic';
SET LOCAL password_encryption = 'scram-sha-256';
-- Stable, schema-qualified names in the generated statements below.
SET LOCAL search_path = pg_catalog;

-- ---------------------------------------------------------------------------- guards
SELECT format('DO $d$ BEGIN RAISE EXCEPTION %L; END $d$', 'db-roles: ' || msg)
  FROM (
    SELECT 'owner and app roles must be different' AS msg WHERE :'owner_role' = :'app_role'
    UNION ALL
    SELECT format('%s is a superuser; the owner and app roles must be ordinary roles', rolname)
      FROM pg_roles WHERE rolname IN (:'owner_role', :'app_role') AND rolsuper
    UNION ALL
    SELECT format('%s is the connecting role; run this as a separate superuser', current_user)
     WHERE current_user IN (:'owner_role', :'app_role')
  ) AS problems
\gexec

\if :set_passwords
\else
-- After a restore (no passwords at hand) the roles must already exist.
SELECT format('DO $d$ BEGIN RAISE EXCEPTION %L; END $d$',
              format('db-roles: role %s does not exist; run infra/db-roles.sh on the host first', r))
  FROM unnest(ARRAY[:'owner_role', :'app_role']) AS r
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r)
\gexec
\endif

-- ---------------------------------------------------------------------------- roles
SELECT format('CREATE ROLE %I', r)
  FROM unnest(ARRAY[:'owner_role', :'app_role']) AS r
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r)
\gexec

ALTER ROLE :"owner_role" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT;
-- NOINHERIT and no memberships: the app role never acts with anyone else's rights.
ALTER ROLE :"app_role" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

SELECT format('REVOKE %I FROM %I GRANTED BY %I', g.rolname, m.rolname, gr.rolname)
  FROM pg_auth_members am
  JOIN pg_roles g ON g.oid = am.roleid
  JOIN pg_roles m ON m.oid = am.member
  JOIN pg_roles gr ON gr.oid = am.grantor
 WHERE m.rolname = :'app_role'
\gexec

\if :set_passwords
ALTER ROLE :"owner_role" PASSWORD :'owner_pw';
ALTER ROLE :"app_role" PASSWORD :'app_pw';
\endif

-- ---------------------------------------------------------------------------- database
SELECT format('ALTER DATABASE %I OWNER TO %I', current_database(), :'owner_role')
\gexec
-- Only named roles connect: PUBLIC loses CONNECT and TEMPORARY.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database())
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM %I', current_database(), :'app_role')
\gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_role')
\gexec

-- ---------------------------------------------------------------------------- schema public
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM :"app_role";
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT USAGE, CREATE ON SCHEMA public TO :"owner_role";

-- ---------------------------------------------------------------------------- ownership
-- Existing installs and restores made every object as the superuser: hand them to the owner.
-- Extension members stay with their extension; sequences that belong to a column (serial,
-- identity) follow their table.
SELECT format('ALTER %s %I.%I OWNER TO %I',
              CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW'
                             WHEN 'S' THEN 'SEQUENCE' WHEN 'f' THEN 'FOREIGN TABLE'
                             ELSE 'TABLE' END,
              n.nspname, c.relname, :'owner_role')
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
   AND c.relowner <> (SELECT oid FROM pg_roles WHERE rolname = :'owner_role')
   AND NOT EXISTS (SELECT FROM pg_depend d
                    WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
   AND NOT (c.relkind = 'S' AND EXISTS (
              SELECT FROM pg_depend d
               WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid
                 AND d.refclassid = 'pg_class'::regclass AND d.deptype IN ('a', 'i')))
 ORDER BY c.relkind = 'S', c.oid
\gexec

SELECT format('ALTER %s %s OWNER TO %I',
              CASE p.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END,
              p.oid::regprocedure, :'owner_role')
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.proowner <> (SELECT oid FROM pg_roles WHERE rolname = :'owner_role')
   AND NOT EXISTS (SELECT FROM pg_depend d
                    WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
 ORDER BY p.oid
\gexec

-- Domains, enums, ranges and standalone composite types (table row types follow the table).
SELECT format('ALTER %s %s OWNER TO %I',
              CASE t.typtype WHEN 'd' THEN 'DOMAIN' ELSE 'TYPE' END, t.oid::regtype, :'owner_role')
  FROM pg_type t
  JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = 'public'
   AND t.typowner <> (SELECT oid FROM pg_roles WHERE rolname = :'owner_role')
   AND (t.typtype IN ('d', 'e', 'r')
        OR (t.typtype = 'c' AND (SELECT relkind FROM pg_class WHERE oid = t.typrelid) = 'c'))
   AND NOT EXISTS (SELECT FROM pg_depend d
                    WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
 ORDER BY t.oid
\gexec

-- ---------------------------------------------------------------------------- app privileges
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_role";
REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM :"app_role";
SELECT format('REVOKE MAINTAIN ON ALL TABLES IN SCHEMA public FROM %I', :'app_role')
 WHERE current_setting('server_version_num')::int >= 170000
\gexec
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_role";
REVOKE UPDATE ON ALL SEQUENCES IN SCHEMA public FROM :"app_role";
GRANT EXECUTE ON ALL ROUTINES IN SCHEMA public TO :"app_role";

-- Tables, sequences and functions that later migrations create (as the owner) get the same
-- grants automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLES FROM :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  REVOKE UPDATE ON SEQUENCES FROM :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT EXECUTE ON ROUTINES TO :"app_role";

COMMIT;
