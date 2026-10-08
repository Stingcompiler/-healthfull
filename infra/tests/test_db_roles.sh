#!/usr/bin/env bash
# Tests for the database roles (infra/db/roles.sh + roles.sql, infra/db-roles.sh, and the
# role step of infra/backup/restore-dump.sh).
#   A. infra/db-roles.sh against the fake docker: password generation in .env, idempotency,
#      refusals, verification failures. Always runs.
#   B. roles.sql against a real PostgreSQL 16 (local socket or PG* env, as a superuser): an
#      install made before the roles existed is handed to the owner; the app role can read and
#      write rows but cannot TRUNCATE, ALTER, DROP, create objects or disable triggers; tables
#      that later migrations create reach the app role; restores are re-granted. Uses uniquely
#      named roles and databases and drops only those. Skips when no server is reachable
#      unless REQUIRE_PG=1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
INFRA="$(cd "$HERE/.." && pwd -P)"
# shellcheck source=infra/tests/testlib.sh
source "$HERE/testlib.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-roles-test.XXXXXX")"
CLEANUP_PG=0
cleanup() {
  if [[ $CLEANUP_PG -eq 1 ]]; then
    local db
    for db in $(psql -X -w -tA -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE 'infra_test_%$ID%'" 2>/dev/null); do
      case "$db" in
        infra_test_*"$ID"*) psql -X -w -q -d postgres -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null 2>&1 || true ;;
      esac
    done
    psql -X -w -q -d postgres -c "DROP ROLE IF EXISTS \"$OWNER\"" -c "DROP ROLE IF EXISTS \"$APP\"" >/dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# ================================================================ A. infra/db-roles.sh (fake docker)
export FAKE_STATE="$WORK/fake"
export ENV_FILE="$WORK/.env"
host_setup() {
  rm -rf "$FAKE_STATE"
  mkdir -p "$FAKE_STATE"
  echo "v1" >"$FAKE_STATE/running"
  printf 'COMPOSE_PROJECT_NAME=hospital\nPOSTGRES_USER=hospital\nPOSTGRES_PASSWORD=x\nDB_NAME=hospital\n' >"$ENV_FILE"
  # No trailing newline on purpose: a generated line must not be glued onto the last one.
  printf 'TZ=Africa/Khartoum' >>"$ENV_FILE"
  chmod 600 "$ENV_FILE"
  unset FAKE_ROLES_EXIT FAKE_VERIFY_OUTPUT DB_OWNER_PASSWORD DB_APP_PASSWORD DB_OWNER_USER DB_APP_USER || true
}
run_host() {
  set +e
  PATH="$HERE/fake-docker:$PATH" "$INFRA/db-roles.sh" "$@" >"$WORK/out.log" 2>&1
  CODE=$?
  set -e
}
show_and_fail() {
  echo "--- calls"; cat "$FAKE_STATE/calls.log" 2>/dev/null || true; echo "--- output"; cat "$WORK/out.log"
  fail "$1"
}
env_val() { grep "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-; }

host_setup
run_host
[[ $CODE -eq 0 ]] || show_and_fail "first run must succeed, got $CODE"
owner_pw="$(env_val DB_OWNER_PASSWORD)"
app_pw="$(env_val DB_APP_PASSWORD)"
assert_match "$owner_pw" '^[0-9a-f]{48}$' "generated owner password"
assert_match "$app_pw" '^[0-9a-f]{48}$' "generated app password"
[[ "$owner_pw" != "$app_pw" ]] || fail "the two generated passwords must differ"
grep -q '^TZ=Africa/Khartoum$' "$ENV_FILE" || fail "last line of .env kept intact"
assert_eq "$(stat -c %a "$ENV_FILE" 2>/dev/null || stat -f %Lp "$ENV_FILE")" "600" ".env keeps its mode"
[[ -z "$(find "$WORK" -maxdepth 1 -name '.env.update.*')" ]] || fail "temp env file left"
grep -q "^\\\\set owner_pw '$owner_pw'$" "$FAKE_STATE/roles-apply.sql" || show_and_fail "owner password from .env"
grep -q "^\\\\set app_role 'hospital_app'$" "$FAKE_STATE/roles-apply.sql" || show_and_fail "default app role name"
grep -q "^\\\\set owner_role 'hospital_owner'$" "$FAKE_STATE/roles-apply.sql" || show_and_fail "default owner role name"
grep -q "PROBLEM: " "$FAKE_STATE/roles-verify.sql" || show_and_fail "verification ran"
grep -qs -e "$owner_pw" -e "$app_pw" "$FAKE_STATE/calls.log" && show_and_fail "a password reached a docker command line"
grep -q 'compose exec -T db sh -c' "$FAKE_STATE/calls.log" || show_and_fail "psql runs inside the db container"
pass "db-roles.sh: generates missing role passwords atomically, applies and verifies through stdin"

before="$(sha256 "$ENV_FILE")"
run_host
[[ $CODE -eq 0 ]] || show_and_fail "second run must succeed"
assert_eq "$(sha256 "$ENV_FILE")" "$before" ".env unchanged by a re-run"
pass "db-roles.sh: idempotent; existing passwords are never replaced"

host_setup
before="$(sha256 "$ENV_FILE")"
run_host --no-generate
assert_eq "$CODE" "2" "--no-generate without passwords"
assert_eq "$(sha256 "$ENV_FILE")" "$before" ".env untouched"
[[ -f "$FAKE_STATE/calls.log" ]] && show_and_fail "no docker call when passwords are missing"
pass "db-roles.sh --no-generate: refuses without role passwords and changes nothing"

host_setup
printf '\nDB_OWNER_PASSWORD=short\nDB_APP_PASSWORD=%s\n' "$app_pw" >>"$ENV_FILE"
run_host
assert_eq "$CODE" "2" "invalid password"
grep -q "16-128 characters" "$WORK/out.log" || show_and_fail "password rule explained"
[[ -f "$FAKE_STATE/calls.log" ]] && show_and_fail "no docker call with an invalid password"
host_setup
printf '\nDB_OWNER_PASSWORD=%s\nDB_APP_PASSWORD=%s\n' "$app_pw" "$app_pw" >>"$ENV_FILE"
run_host
assert_eq "$CODE" "2" "identical passwords"
host_setup
printf '\nDB_APP_USER=hospital\n' >>"$ENV_FILE"
run_host
assert_eq "$CODE" "2" "app role = POSTGRES_USER"
grep -q "superuser" "$WORK/out.log" || show_and_fail "superuser refusal explained"
pass "db-roles.sh: refuses weak or shared passwords and the superuser as a role, before docker"

host_setup
export FAKE_ROLES_EXIT=3
run_host
assert_eq "$CODE" "1" "apply failure"
[[ -f "$FAKE_STATE/roles-verify.sql" ]] && show_and_fail "no verification after a failed apply"
host_setup
export FAKE_VERIFY_OUTPUT="PROBLEM: hospital owns public.billing_invoice"
run_host
assert_eq "$CODE" "1" "verification problem"
grep -q "PROBLEM: hospital owns public.billing_invoice" "$WORK/out.log" || show_and_fail "problem printed"
pass "db-roles.sh: a failed apply or a verification problem exits 1 with the details"
unset FAKE_ROLES_EXIT FAKE_VERIFY_OUTPUT

# ================================================================ B. roles.sql on PostgreSQL
unset ENV_FILE
if ! pg_isready -q -d postgres 2>/dev/null; then
  if [[ "${REQUIRE_PG:-0}" == "1" ]]; then
    echo "FAIL: PostgreSQL not reachable and REQUIRE_PG=1" >&2
    exit 1
  fi
  echo "SKIP: PostgreSQL part (not reachable; set PGHOST/PGPORT/PGUSER/PGPASSWORD)"
  summary
  exit 0
fi

ID="$(printf '%s' "$$-$(date +%s)" | (sha1sum 2>/dev/null || shasum -a 1) | cut -c1-8)"
OWNER="infra_test_owner_$ID"
APP="infra_test_app_$ID"
DB="infra_test_roles_$ID"
TGT="infra_test_roles_tgt_$ID"
OWNER_PW="owner-test-only-$ID-0123456789"
APP_PW="app-test-only-$ID-0123456789"
CLEANUP_PG=1
ROLES="$INFRA/db/roles.sh"
SUPER="$(psql -X -w -tA -d postgres -c 'SELECT current_user')"

sql() { psql -X -w -v ON_ERROR_STOP=1 -q -tA -d "$1" -c "$2"; }
roles() { DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" DB_OWNER_PASSWORD="$OWNER_PW" DB_APP_PASSWORD="$APP_PW" "$ROLES" "$@"; }
as_role() {
  # as_role DB ROLE PASSWORD SQL: the same server, logged in as ROLE (PGPASSWORD for TCP).
  PGUSER="$2" PGPASSWORD="$3" psql -X -w -v ON_ERROR_STOP=1 -q -tA -d "$1" -c "$4"
}
as_app() { as_role "${2:-$DB}" "$APP" "$APP_PW" "$1"; }
as_owner() { as_role "$DB" "$OWNER" "$OWNER_PW" "$1"; }
app_refused() {
  # app_refused SQL EXPECTED_ERROR_TEXT
  local out
  if out="$(as_app "$1" 2>&1)"; then fail "the app role was allowed to run: $1"; fi
  [[ "$out" == *"$2"* ]] || fail "'$1' failed for another reason than '$2': $out"
}

# ---------------------------------------------------------------- an install made before the roles
sql postgres "CREATE DATABASE \"$DB\""
sql "$DB" "
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE django_migrations (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, app text, name text);
INSERT INTO django_migrations (app, name) VALUES ('core', '0001_initial');
CREATE TABLE billing_invoice (id serial PRIMARY KEY, total numeric(14,2) NOT NULL, status text NOT NULL);
INSERT INTO billing_invoice (total, status) VALUES (10000.00, 'approved'), (500.00, 'draft');
CREATE FUNCTION frozen_guard() RETURNS trigger LANGUAGE plpgsql AS \$\$
BEGIN IF OLD.status = 'approved' THEN RAISE EXCEPTION 'INVOICE_FROZEN'; END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END \$\$;
CREATE TRIGGER invoice_frozen BEFORE UPDATE OR DELETE ON billing_invoice
  FOR EACH ROW EXECUTE FUNCTION frozen_guard();
CREATE SEQUENCE doc_number;
CREATE VIEW open_invoices AS SELECT * FROM billing_invoice WHERE status = 'draft';
CREATE FUNCTION hs_normalize_text(value text) RETURNS text LANGUAGE sql IMMUTABLE AS \$\$ SELECT lower(value) \$\$;
CREATE TYPE invoice_state AS ENUM ('draft', 'approved');
"
out="$(DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" "$ROLES" --db "$DB" --verify 2>/dev/null || true)"
assert_match "$out" "role $APP does not exist" "verify reports missing roles"
assert_match "$out" "$SUPER owns public.billing_invoice" "verify reports superuser-owned tables"
pass "verify lists what an install made before the roles gets wrong"

roles --db "$DB" 2>"$WORK/apply.err" || { cat "$WORK/apply.err" >&2; fail "apply failed"; }
roles --db "$DB" --verify >"$WORK/verify.out" 2>&1 || { cat "$WORK/verify.out" >&2; fail "verify after apply"; }
assert_eq "$(sql "$DB" "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")" "$OWNER" "database owner"
assert_eq "$(sql "$DB" "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r','S','v') AND relowner <> '$OWNER'::regrole")" "0" "every table, sequence and view owned by the owner"
assert_eq "$(sql "$DB" "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'frozen_guard'")" "$OWNER" "trigger function owned by the owner"
assert_eq "$(sql "$DB" "SELECT pg_get_userbyid(typowner) FROM pg_type WHERE typname = 'invoice_state'")" "$OWNER" "enum owned by the owner"
assert_eq "$(sql postgres "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname = '$APP'")" "f" "app role has no dangerous attribute"
assert_eq "$(sql postgres "SELECT rolinherit FROM pg_roles WHERE rolname = '$APP'")" "f" "app role is NOINHERIT"
assert_eq "$(sql postgres "SELECT left(rolpassword, 14) FROM pg_authid WHERE rolname = '$APP'")" 'SCRAM-SHA-256$' "app password stored as SCRAM"
pass "apply: roles created, the database and every object handed to the owner, verify clean"

# ---------------------------------------------------------------- what the app role can and cannot do
assert_eq "$(as_app "SELECT count(*) FROM billing_invoice")" "2" "app reads"
as_app "INSERT INTO billing_invoice (total, status) VALUES (1.00, 'draft')" || fail "app inserts (serial)"
as_app "INSERT INTO django_migrations (app, name) VALUES ('x', 'y')" || fail "app inserts (identity)"
as_app "UPDATE billing_invoice SET total = 2.00 WHERE status = 'draft'" || fail "app updates rows"
as_app "DELETE FROM billing_invoice WHERE total = 2.00 AND status = 'draft'" || fail "app deletes rows"
as_app "SELECT nextval('doc_number'), hs_normalize_text('ABC'), similarity('abc', 'abd') > 0" >/dev/null || fail "app uses sequences and functions"
as_app "SELECT count(*) FROM open_invoices" >/dev/null || fail "app reads views"
pass "app role: SELECT, INSERT, UPDATE, DELETE, sequences, functions, views"

app_refused "UPDATE billing_invoice SET total = 1 WHERE status = 'approved'" "INVOICE_FROZEN"
app_refused "TRUNCATE billing_invoice" "permission denied"
app_refused "ALTER TABLE billing_invoice DISABLE TRIGGER invoice_frozen" "must be owner"
app_refused "ALTER TABLE billing_invoice DISABLE TRIGGER ALL" "must be owner"
app_refused "DROP TRIGGER invoice_frozen ON billing_invoice" "must be owner"
app_refused "SET session_replication_role = replica" "permission denied"
app_refused "ALTER TABLE billing_invoice ADD COLUMN x int" "must be owner"
app_refused "DROP TABLE billing_invoice" "must be owner"
app_refused "CREATE TABLE evil (id int)" "permission denied"
app_refused "CREATE TEMP TABLE evil (id int)" "permission denied"
app_refused "CREATE SCHEMA evil" "permission denied"
app_refused "CREATE OR REPLACE FUNCTION public.frozen_guard() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'" "permission denied"
app_refused "SELECT setval('doc_number', 1)" "permission denied"
app_refused "ALTER ROLE $APP SUPERUSER" "permission denied"
app_refused "GRANT $OWNER TO $APP" "permission denied"
pass "app role cannot TRUNCATE, ALTER, DROP, disable triggers, create objects, setval or escalate"

# ---------------------------------------------------------------- migrations as the owner
as_owner "CREATE TABLE ledger_journalline (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, amount numeric(14,2));
          CREATE FUNCTION later_fn() RETURNS int LANGUAGE sql AS 'SELECT 1';
          CREATE EXTENSION IF NOT EXISTS btree_gin;
          ALTER TABLE billing_invoice ADD COLUMN note text;
          CREATE OR REPLACE FUNCTION frozen_guard() RETURNS trigger LANGUAGE plpgsql AS \$\$
          BEGIN IF OLD.status = 'approved' THEN RAISE EXCEPTION 'INVOICE_FROZEN'; END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END \$\$;" ||
  fail "the owner runs DDL (tables, functions, trusted extensions, triggers)"
as_app "INSERT INTO ledger_journalline (amount) VALUES (5.00)" || fail "a table created later reaches the app role"
assert_eq "$(as_app "SELECT later_fn()")" "1" "a function created later reaches the app role"
app_refused "TRUNCATE ledger_journalline" "permission denied"
roles --db "$DB" --verify >"$WORK/verify2.out" 2>&1 || { cat "$WORK/verify2.out" >&2; fail "verify after owner DDL"; }
pass "owner (migrations) can change the schema; new tables and functions reach the app role, TRUNCATE does not"

# ---------------------------------------------------------------- idempotent and self-repairing
sql postgres "GRANT \"$OWNER\" TO \"$APP\""
sql "$DB" "GRANT TRUNCATE ON billing_invoice TO \"$APP\"; ALTER SEQUENCE doc_number OWNER TO \"$SUPER\""
out="$(roles --db "$DB" --verify 2>/dev/null || true)"
assert_match "$out" "app role is a member of role $OWNER" "membership reported"
assert_match "$out" "app role holds TRUNCATE on public.billing_invoice" "TRUNCATE grant reported"
assert_match "$out" "$SUPER owns public.doc_number" "foreign owner reported"
roles --db "$DB" 2>/dev/null || fail "re-apply"
roles --db "$DB" 2>/dev/null || fail "second re-apply"
DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" "$ROLES" --db "$DB" --no-passwords 2>/dev/null || fail "apply without passwords"
roles --db "$DB" --verify >"$WORK/verify3.out" 2>&1 || { cat "$WORK/verify3.out" >&2; fail "verify after repair"; }
assert_eq "$(sql postgres "SELECT count(*) FROM pg_auth_members WHERE member = '$APP'::regrole")" "0" "membership revoked"
pass "re-applying is idempotent and repairs memberships, stray grants and foreign owners"

# ---------------------------------------------------------------- guards
before="$(sql postgres "SELECT rolsuper FROM pg_roles WHERE rolname = '$SUPER'")"
if DB_OWNER_USER="$SUPER" DB_APP_USER="$APP" DB_OWNER_PASSWORD="$OWNER_PW" DB_APP_PASSWORD="$APP_PW" \
  "$ROLES" --db "$DB" >/dev/null 2>"$WORK/guard.err"; then
  fail "a superuser must never be accepted as the owner role"
fi
grep -q "superuser" "$WORK/guard.err" || { cat "$WORK/guard.err" >&2; fail "superuser guard message"; }
assert_eq "$(sql postgres "SELECT rolsuper FROM pg_roles WHERE rolname = '$SUPER'")" "$before" "superuser untouched"
if DB_OWNER_USER="infra_test_nobody_$ID" DB_APP_USER="$APP" "$ROLES" --db "$DB" --no-passwords >/dev/null 2>"$WORK/guard2.err"; then
  fail "--no-passwords must not create roles"
fi
grep -q "does not exist" "$WORK/guard2.err" || { cat "$WORK/guard2.err" >&2; fail "missing role message"; }
assert_eq "$(sql postgres "SELECT count(*) FROM pg_roles WHERE rolname = 'infra_test_nobody_$ID'")" "0" "no role created"
pass "guards: a superuser is never used as a role; without passwords nothing is created"

# ---------------------------------------------------------------- restore-dump re-grants
pg_dump -Fc -f "$WORK/roles.dump" "$DB"
sql postgres "CREATE DATABASE \"$TGT\""
sql "$TGT" "CREATE TABLE marker (v text); INSERT INTO marker VALUES ('old');"
DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" \
  "$INFRA/backup/restore-dump.sh" --dump "$WORK/roles.dump" --target "$TGT" --yes >/dev/null 2>"$WORK/rd.err" || {
  cat "$WORK/rd.err" >&2
  fail "restore-dump with roles failed"
}
assert_eq "$(sql "$TGT" "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")" "$OWNER" "restored database owned by the owner"
DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" "$ROLES" --db "$TGT" --verify >"$WORK/verify4.out" 2>&1 ||
  { cat "$WORK/verify4.out" >&2; fail "restored database verify"; }
assert_eq "$(as_app "SELECT count(*) FROM billing_invoice WHERE status = 'approved'" "$TGT")" "1" "app reads the restored data"
as_app "INSERT INTO ledger_journalline (amount) VALUES (1.00)" "$TGT" || fail "app writes to the restored database"
if as_app "UPDATE billing_invoice SET total = 1 WHERE status = 'approved'" "$TGT" 2>/dev/null; then
  fail "restored trigger must still block the app role"
fi
pass "restore-dump hands the restored database to the owner and re-grants the app role before the swap"

sql postgres "CREATE DATABASE \"${TGT}_2\""
sql "${TGT}_2" "CREATE TABLE marker (v text); INSERT INTO marker VALUES ('live');"
if DB_OWNER_USER="$OWNER" DB_APP_USER="infra_test_nobody_$ID" \
  "$INFRA/backup/restore-dump.sh" --dump "$WORK/roles.dump" --target "${TGT}_2" --yes >/dev/null 2>"$WORK/rd2.err"; then
  fail "restore-dump must fail when the roles cannot be applied"
fi
grep -q "live database ${TGT}_2 untouched" "$WORK/rd2.err" || { cat "$WORK/rd2.err" >&2; fail "restore failure message"; }
assert_eq "$(sql "${TGT}_2" "SELECT v FROM marker")" "live" "live database untouched"
assert_eq "$(sql postgres "SELECT count(*) FROM pg_database WHERE datname LIKE '${TGT}_2_incoming_%'")" "0" "incoming database dropped"
pass "restore-dump refuses to swap in a database the roles could not be applied to"

summary
