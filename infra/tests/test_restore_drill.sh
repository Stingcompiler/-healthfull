#!/usr/bin/env bash
# Restore-from-scratch drill (infra/backup/restore-drill.sh) against a real PostgreSQL 16 and the
# real backend: a database migrated and seeded through the services (seed_e2e plus a day of
# cashier work, shifts and an answered insurance claim) is backed up with backup-nightly.sh,
# rebuilt into a brand new database with freshly created owner and app roles, checked with
# `manage.py migrate --check` (owner) and `manage.py integrity_check` (app role), and its row
# counts compared with the source. A damaged ledger must fail the drill.
#
# Needs PostgreSQL (skips unless REQUIRE_PG=1) and the backend environment (uv and
# backend/.venv; skips the Django part unless REQUIRE_DJANGO=1). Uses uniquely named databases
# and roles and drops only those.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/../.." && pwd -P)"
BK="$ROOT/infra/backup"
# shellcheck source=infra/tests/testlib.sh
source "$HERE/testlib.sh"

if ! pg_isready -q -d postgres 2>/dev/null; then
  if [[ "${REQUIRE_PG:-0}" == "1" ]]; then
    echo "FAIL: PostgreSQL not reachable and REQUIRE_PG=1" >&2
    exit 1
  fi
  echo "SKIP: PostgreSQL not reachable (set PGHOST/PGPORT/PGUSER/PGPASSWORD)"
  exit 0
fi
if ! command -v uv >/dev/null 2>&1 || [[ ! -d "$ROOT/backend/.venv" ]]; then
  if [[ "${REQUIRE_DJANGO:-0}" == "1" ]]; then
    echo "FAIL: uv or backend/.venv missing and REQUIRE_DJANGO=1 (run: make setup-backend)" >&2
    exit 1
  fi
  echo "SKIP: the backend environment is missing (uv, backend/.venv): make setup-backend"
  exit 0
fi

ID="$(printf '%s' "$$-$(date +%s)" | (sha1sum 2>/dev/null || shasum -a 1) | cut -c1-8)"
SRC="test_infra_drill_src_$ID"
TGT="test_infra_drill_tgt_$ID"
OWNER="infra_test_drill_owner_$ID"
APP="infra_test_drill_app_$ID"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-drill-test.XXXXXX")"
export BACKUP_DIR="$WORK/backups"
LOG="$BACKUP_DIR/status/restore-tests.jsonl"
MANAGE="uv run --directory $ROOT/backend python manage.py"

cleanup() {
  local db
  for db in $(psql -X -w -tA -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE 'test_infra_drill_%$ID%'" 2>/dev/null); do
    case "$db" in
      test_infra_drill_*"$ID"*) psql -X -w -q -d postgres -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null 2>&1 || true ;;
    esac
  done
  psql -X -w -q -d postgres -c "DROP ROLE IF EXISTS \"$OWNER\"" -c "DROP ROLE IF EXISTS \"$APP\"" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

sql() { psql -X -w -v ON_ERROR_STOP=1 -q -tA -d "$1" -c "$2"; }
src_manage() {
  # shellcheck disable=SC2086 # MANAGE is a command line, split on purpose
  DB_NAME="$SRC" DJANGO_DEBUG=1 $MANAGE "$@"
}
drill() {
  set +e
  DB_OWNER_USER="$OWNER" DB_APP_USER="$APP" \
    DB_OWNER_PASSWORD="owner-test-only-$ID-0123456789" DB_APP_PASSWORD="app-test-only-$ID-0123456789" \
    "$BK/restore-drill.sh" --manage "$MANAGE" "$@" >"$WORK/drill.out" 2>&1
  CODE=$?
  set -e
}
show_and_fail() {
  cat "$WORK/drill.out" >&2
  fail "$1"
}

# ---------------------------------------------------------------- a seeded source database
sql postgres "CREATE DATABASE \"$SRC\""
src_manage migrate --noinput >"$WORK/migrate.log" 2>&1 || { tail -n 20 "$WORK/migrate.log" >&2; fail "migrate source"; }
src_manage seed_e2e >"$WORK/seed.log" 2>&1 || { tail -n 20 "$WORK/seed.log" >&2; fail "seed_e2e"; }
for spec in 'reports_day {}' 'cashier_screens {}' \
  'claims_case {"stage":"answered","services":["PRC-ECG","LAB-CBC"],"outcomes":["partial","rejected"]}'; do
  name="${spec%% *}"
  src_manage e2e_fixture "$name" --params "${spec#* }" >>"$WORK/seed.log" 2>&1 ||
    { tail -n 20 "$WORK/seed.log" >&2; fail "fixture $name"; }
done
src_manage integrity_check >/dev/null 2>&1 || fail "the seeded source must pass the integrity check"
lines="$(sql "$SRC" "SELECT count(*) FROM ledger_journalline")"
[[ "$lines" -gt 10 ]] || fail "the source has money in the ledger (got $lines lines)"
pass "source: migrated, seeded through the services, ledger in use, integrity check clean"

dump="$(DB_NAME="$SRC" "$BK/backup-nightly.sh" --label drill-src 2>"$WORK/backup.err")" || {
  cat "$WORK/backup.err" >&2
  fail "backup-nightly"
}
assert_file "$dump"

# ---------------------------------------------------------------- the drill passes
drill --dump "$dump" --target "$TGT"
[[ $CODE -eq 0 ]] || show_and_fail "the drill must pass on a good dump (exit $CODE)"
assert_json_field "$LOG" -1 type restore_test
assert_json_field "$LOG" -1 label drill
assert_json_field "$LOG" -1 status ok
assert_json_field "$LOG" -1 roles ok
assert_json_field "$LOG" -1 migrations_check ok
assert_json_field "$LOG" -1 integrity_check ok
assert_json_field "$LOG" -1 integrity.ok True
assert_json_field "$LOG" -1 integrity.checks.ledger_balanced.ok True
assert_json_field "$LOG" -1 integrity.checks.invoice_positions.ok True
assert_json_field "$LOG" -1 integrity.checks.stock.ok True
assert_json_field "$LOG" -1 integrity.checks.allocations.ok True
assert_json_field "$LOG" -1 target_db "$TGT"
assert_eq "$(sql postgres "SELECT count(*) FROM pg_database WHERE datname LIKE '${TGT}%'")" "0" "drill databases dropped"
pass "drill: new database with new roles, migrate --check (owner) and integrity_check (app) pass"

for t in core_user billing_invoice payments_payment payments_allocation ledger_journalline pharmacy_stockmove claims_claim; do
  assert_json_field "$LOG" -1 "tables.$t" "$(sql "$SRC" "SELECT count(*) FROM $t")"
done
pass "row counts of the key tables equal the source"

# ---------------------------------------------------------------- kept database: owner and app roles
drill --dump "$dump" --target "$TGT" --keep
[[ $CODE -eq 0 ]] || show_and_fail "drill with --keep"
assert_eq "$(sql "$TGT" "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")" "$OWNER" "owned by the owner role"
assert_eq "$(sql "$TGT" "SELECT count(*) FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND relowner <> '$OWNER'::regrole")" "0" "every table owned by the owner"
assert_eq "$(sql "$TGT" "SELECT has_table_privilege('$APP', 'ledger_journalline', 'INSERT') AND NOT has_table_privilege('$APP', 'ledger_journalline', 'TRUNCATE')")" "t" "app role: DML, no TRUNCATE"
drill --dump "$dump" --target "$TGT"
assert_eq "$CODE" "1" "an existing target is refused"
grep -q "already exists" "$WORK/drill.out" || show_and_fail "existing target message"
assert_eq "$(sql "$TGT" "SELECT count(*) FROM core_user")" "$(sql "$SRC" "SELECT count(*) FROM core_user")" "kept database untouched"
sql postgres "DROP DATABASE \"$TGT\" WITH (FORCE)"
pass "--keep leaves an owner-owned database the app role can use but not truncate; an existing target is never touched"

# ---------------------------------------------------------------- a damaged ledger fails the drill
sql "$SRC" "SET session_replication_role = replica;
  INSERT INTO ledger_journalentry (source_type, source_id, entry_date, memo, posted_at)
       VALUES ('payment', 999999, current_date, 'drill damage', now());
  INSERT INTO ledger_journalline (entry_id, account_id, debit, credit, service_kind, memo)
       SELECT max(e.id), (SELECT id FROM ledger_account WHERE code = 'CASH_SAFE'), 10, 0, '', ''
         FROM ledger_journalentry e;"
bad="$(DB_NAME="$SRC" "$BK/backup-nightly.sh" --label drill-damaged 2>"$WORK/backup2.err")" || {
  cat "$WORK/backup2.err" >&2
  fail "backup of the damaged source"
}
drill --dump "$bad" --target "$TGT"
assert_eq "$CODE" "1" "a damaged ledger fails the drill"
assert_json_field "$LOG" -1 status failed
assert_json_field "$LOG" -1 integrity_check failed
assert_json_field "$LOG" -1 integrity.checks.ledger_balanced.ok False
assert_json_contains "$LOG" -1 error "integrity_check failed"
assert_eq "$(sql postgres "SELECT count(*) FROM pg_database WHERE datname LIKE '${TGT}%'")" "0" "failed drill database dropped"
pass "a dump with an unbalanced ledger fails the drill, is recorded as failed and dropped"

# ---------------------------------------------------------------- a corrupt dump fails early
printf 'corrupt' >>"$bad"
drill --dump "$bad" --target "$TGT"
assert_eq "$CODE" "1" "corrupt dump"
assert_json_field "$LOG" -1 status failed
assert_json_contains "$LOG" -1 error "restore-dump failed"
assert_json_field "$LOG" -1 migrations_check "not run"
pass "a dump whose checksum no longer matches is refused before any check"

summary
