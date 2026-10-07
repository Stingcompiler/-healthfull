-- hospital-sys database roles: report every way the target database differs from the set-up
-- that infra/db/roles.sql makes. One line per problem, prefixed "PROBLEM:"; no line = all good.
-- Read only. Run by infra/db/roles.sh --verify (variables owner_role, app_role).

\set ON_ERROR_STOP on
SET client_min_messages = warning;
SET search_path = pg_catalog;

WITH
owner_r AS (SELECT oid FROM pg_roles WHERE rolname = :'owner_role'),
app_r AS (SELECT oid FROM pg_roles WHERE rolname = :'app_role'),
ext_member AS (SELECT classid, objid FROM pg_depend WHERE deptype = 'e'),
problems AS (
  -- roles
  SELECT format('role %s does not exist', r) AS problem
    FROM unnest(ARRAY[:'owner_role', :'app_role']) AS r
   WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = r)
  UNION ALL
  SELECT format('role %s is superuser, createdb, createrole, replication or bypassrls', rolname)
    FROM pg_roles
   WHERE rolname IN (:'owner_role', :'app_role')
     AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
  UNION ALL
  SELECT format('role %s cannot log in', rolname)
    FROM pg_roles WHERE rolname IN (:'owner_role', :'app_role') AND NOT rolcanlogin
  UNION ALL
  SELECT format('app role is a member of role %s', g.rolname)
    FROM pg_auth_members am JOIN pg_roles g ON g.oid = am.roleid
   WHERE am.member = (SELECT oid FROM app_r)
  -- database and schema
  UNION ALL
  SELECT format('database %s is owned by %s, not %s',
                d.datname, pg_get_userbyid(d.datdba), :'owner_role')
    FROM pg_database d
   WHERE d.datname = current_database() AND d.datdba IS DISTINCT FROM (SELECT oid FROM owner_r)
  UNION ALL
  SELECT 'app role cannot connect to the database'
   WHERE EXISTS (SELECT FROM app_r)
     AND NOT has_database_privilege((SELECT oid FROM app_r), current_database(), 'CONNECT')
  UNION ALL
  SELECT 'app role may create schemas or temporary tables in the database'
   WHERE EXISTS (SELECT FROM app_r)
     AND (has_database_privilege((SELECT oid FROM app_r), current_database(), 'CREATE')
          OR has_database_privilege((SELECT oid FROM app_r), current_database(), 'TEMPORARY'))
  UNION ALL
  SELECT 'app role may create objects in schema public'
   WHERE EXISTS (SELECT FROM app_r) AND has_schema_privilege((SELECT oid FROM app_r), 'public', 'CREATE')
  UNION ALL
  SELECT 'app role has no USAGE on schema public'
   WHERE EXISTS (SELECT FROM app_r) AND NOT has_schema_privilege((SELECT oid FROM app_r), 'public', 'USAGE')
  UNION ALL
  SELECT 'owner role may not create objects in schema public'
   WHERE EXISTS (SELECT FROM owner_r) AND NOT has_schema_privilege((SELECT oid FROM owner_r), 'public', 'CREATE')
  -- ownership
  UNION ALL
  SELECT format('%s owns %s', pg_get_userbyid(c.relowner), c.oid::regclass)
    FROM pg_class c
   WHERE c.relnamespace = 'public'::regnamespace
     AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
     AND c.relowner IS DISTINCT FROM (SELECT oid FROM owner_r)
     AND NOT EXISTS (SELECT FROM ext_member e
                      WHERE e.classid = 'pg_class'::regclass AND e.objid = c.oid)
  UNION ALL
  SELECT format('%s owns function %s', pg_get_userbyid(p.proowner), p.oid::regprocedure)
    FROM pg_proc p
   WHERE p.pronamespace = 'public'::regnamespace
     AND p.proowner IS DISTINCT FROM (SELECT oid FROM owner_r)
     AND NOT EXISTS (SELECT FROM ext_member e
                      WHERE e.classid = 'pg_proc'::regclass AND e.objid = p.oid)
  UNION ALL
  SELECT format('app role owns %s', obj)
    FROM (SELECT c.oid::regclass::text AS obj FROM pg_class c
           WHERE c.relowner = (SELECT oid FROM app_r)
          UNION ALL
          SELECT 'function ' || p.oid::regprocedure::text FROM pg_proc p
           WHERE p.proowner = (SELECT oid FROM app_r)
          UNION ALL
          SELECT 'schema ' || n.nspname FROM pg_namespace n
           WHERE n.nspowner = (SELECT oid FROM app_r)
          UNION ALL
          SELECT 'type ' || t.oid::regtype::text FROM pg_type t
           WHERE t.typowner = (SELECT oid FROM app_r)) AS owned
  -- privileges of the app role on what exists now
  UNION ALL
  SELECT format('app role lacks %s on %s', priv, c.oid::regclass)
    FROM pg_class c CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) AS priv
   WHERE EXISTS (SELECT FROM app_r)
     AND c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
     AND NOT has_table_privilege((SELECT oid FROM app_r), c.oid, priv)
  UNION ALL
  SELECT format('app role holds %s on %s', priv, c.oid::regclass)
    FROM pg_class c CROSS JOIN unnest(ARRAY['TRUNCATE', 'REFERENCES', 'TRIGGER']) AS priv
   WHERE EXISTS (SELECT FROM app_r)
     AND c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
     AND has_table_privilege((SELECT oid FROM app_r), c.oid, priv)
  UNION ALL
  SELECT format('app role lacks USAGE on sequence %s', c.oid::regclass)
    FROM pg_class c
   WHERE EXISTS (SELECT FROM app_r)
     AND c.relnamespace = 'public'::regnamespace AND c.relkind = 'S'
     -- CASE: the planner may test the privilege before relkind, which errors on non-sequences.
     AND CASE WHEN c.relkind = 'S'
              THEN NOT has_sequence_privilege((SELECT oid FROM app_r), c.oid, 'USAGE') END
  UNION ALL
  SELECT format('app role lacks EXECUTE on function %s', p.oid::regprocedure)
    FROM pg_proc p
   WHERE EXISTS (SELECT FROM app_r)
     AND p.pronamespace = 'public'::regnamespace
     AND NOT has_function_privilege((SELECT oid FROM app_r), p.oid, 'EXECUTE')
  -- default privileges: what later migrations (run as the owner) will create
  UNION ALL
  SELECT format('new %s made by migrations would not grant %s to the app role', w.kind, w.priv)
    FROM (VALUES ('r', 'tables', 'SELECT'), ('r', 'tables', 'INSERT'),
                 ('r', 'tables', 'UPDATE'), ('r', 'tables', 'DELETE'),
                 ('S', 'sequences', 'USAGE'), ('S', 'sequences', 'SELECT'),
                 ('f', 'functions', 'EXECUTE')) AS w(objtype, kind, priv)
   WHERE EXISTS (SELECT FROM app_r) AND EXISTS (SELECT FROM owner_r)
     AND NOT EXISTS (
       SELECT FROM pg_default_acl da, aclexplode(da.defaclacl) a
        WHERE da.defaclrole = (SELECT oid FROM owner_r)
          AND da.defaclnamespace = 'public'::regnamespace
          AND da.defaclobjtype = w.objtype::"char"
          AND a.grantee = (SELECT oid FROM app_r)
          AND a.privilege_type = w.priv)
  UNION ALL
  SELECT format('new tables made by migrations would grant %s to the app role', a.privilege_type)
    FROM pg_default_acl da, aclexplode(da.defaclacl) a
   WHERE da.defaclrole = (SELECT oid FROM owner_r)
     AND da.defaclobjtype = 'r'
     AND a.grantee = (SELECT oid FROM app_r)
     AND a.privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN')
)
SELECT 'PROBLEM: ' || problem FROM problems ORDER BY 1;
