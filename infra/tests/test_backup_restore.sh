#!/usr/bin/env bash
# Integration test for infra/backup against a real PostgreSQL 16 (local socket or PG* env).
# Creates uniquely named throwaway databases and drops only those. Skips (exit 0) when no
# server is reachable unless REQUIRE_PG=1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BK="$(cd "$HERE/../backup" && pwd -P)"
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

ID="$(printf '%s' "$$-$(date +%s)" | (sha1sum 2>/dev/null || shasum -a 1) | cut -c1-8)"
SRC="infra_test_src_$ID"
TGT="infra_test_tgt_$ID"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-backup-test.XXXXXX")"
export BACKUP_DIR="$WORK/backups"

cleanup() {
  local db
  # Only this run's throwaway databases (their names embed $ID). restore-test.sh drops its own
  # scratch databases, which the assertions below verify.
  for db in $(psql -X -w -tA -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE 'infra_test_%$ID%'" 2>/dev/null); do
    case "$db" in
      infra_test_*"$ID"*) psql -X -w -q -d postgres -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null 2>&1 || true ;;
    esac
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

sql() { psql -X -w -v ON_ERROR_STOP=1 -q -tA -d "$1" -c "$2"; }

# ---------------------------------------------------------------- fixture database
sql postgres "CREATE DATABASE \"$SRC\""
sql "$SRC" "
CREATE TABLE django_migrations (id serial PRIMARY KEY, app text, name text, applied timestamptz DEFAULT now());
INSERT INTO django_migrations (app, name) VALUES ('core','0001_initial'),('ops','0001_initial'),('auth','0001_initial');
CREATE TABLE core_user (id serial PRIMARY KEY, username text UNIQUE, full_name_ar text);
INSERT INTO core_user (username, full_name_ar) VALUES ('admin', 'مدير النظام'), ('cashier', 'أمين الصندوق');
CREATE TABLE billing_invoice (id serial PRIMARY KEY, total numeric(14,2) NOT NULL, status text NOT NULL);
INSERT INTO billing_invoice (total, status) VALUES (10000.00, 'approved');
-- An immutability trigger like django-pgtrigger's must survive the dump/restore round trip.
CREATE FUNCTION block_approved() RETURNS trigger LANGUAGE plpgsql AS \$\$
BEGIN IF OLD.status = 'approved' THEN RAISE EXCEPTION 'INVOICE_FROZEN'; END IF; RETURN NEW; END \$\$;
CREATE TRIGGER invoice_frozen BEFORE UPDATE ON billing_invoice FOR EACH ROW EXECUTE FUNCTION block_approved();
CREATE TABLE empty_table (id int);
"
mkdir -p "$WORK/media/logos"
printf 'logo' >"$WORK/media/logos/center.png"

# ---------------------------------------------------------------- 1. nightly backup succeeds
out="$(DB_NAME="$SRC" MEDIA_DIR="$WORK/media" "$BK/backup-nightly.sh" 2>"$WORK/b1.err")" || {
  cat "$WORK/b1.err" >&2
  fail "backup-nightly exited non-zero"
}
dump1="$out"
assert_file "$dump1"
assert_match "$dump1" "^$BACKUP_DIR/dumps/$SRC-[0-9]{8}T[0-9]{6}Z\\.dump\$" "dump path printed on stdout"
assert_file "$dump1.sha256"
assert_eq "$(awk '{print $1}' "$dump1.sha256")" "$(sha256 "$dump1")" "checksum file matches"
assert_eq "$(find "$BACKUP_DIR/dumps" -name '*.partial' | wc -l | tr -d ' ')" "0" "no partial files left"
assert_eq "$(find "$BACKUP_DIR/media" -name '*.tar.gz' | wc -l | tr -d ' ')" "1" "media archived"
tar -tzf "$BACKUP_DIR"/media/*.tar.gz | grep -q 'logos/center.png' || fail "media archive content"
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 status ok
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 type backup
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 database "$SRC"
pass "nightly backup writes a verified dump, checksum, media archive and an ok status line"

# ---------------------------------------------------------------- 2. labelled backup + retention
for i in 1 2 3 4 5; do
  f="$BACKUP_DIR/dumps/$SRC-2020010${i}T000000Z.dump"
  printf 'old' >"$f"
  printf 'x  y\n' >"$f.sha256"
  touch -t "2020010${i}0000" "$f" "$f.sha256"
done
sleep 1 # distinct mtimes for the two real dumps
dump2="$(DB_NAME="$SRC" BACKUP_RETENTION_DAYS=1 BACKUP_KEEP_MIN=3 "$BK/backup-nightly.sh" --label pre-update-v1.2.3 2>"$WORK/b2.err")" || {
  cat "$WORK/b2.err" >&2
  fail "labelled backup failed"
}
assert_match "$dump2" "-pre-update-v1\\.2\\.3\\.dump\$" "label in file name"
remaining="$(find "$BACKUP_DIR/dumps" -maxdepth 1 -name '*.dump' | wc -l | tr -d ' ')"
assert_eq "$remaining" "3" "retention keeps BACKUP_KEEP_MIN newest dumps"
[[ -f "$dump1" && -f "$dump2" ]] || fail "retention must keep the two real dumps"
[[ -f "$BACKUP_DIR/dumps/$SRC-20200105T000000Z.dump" ]] || fail "newest old dump kept as third"
[[ ! -f "$BACKUP_DIR/dumps/$SRC-20200101T000000Z.dump.sha256" ]] || fail "pruned checksum file removed"
assert_json_count "$BACKUP_DIR/status/backup-runs.jsonl" -1 pruned 4
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 label pre-update-v1.2.3
pass "labelled backup and day-based retention with a minimum keep count"

# ---------------------------------------------------------------- 3. restore test passes
RESTORE_TEST_TABLES="django_migrations core_user billing_invoice patients_patient" \
  "$BK/restore-test.sh" 2>"$WORK/r1.err" || {
  cat "$WORK/r1.err" >&2
  fail "restore-test failed on a good dump"
}
LOG="$BACKUP_DIR/status/restore-tests.jsonl"
assert_json_field "$LOG" -1 status ok
assert_json_field "$LOG" -1 dump "$dump2"
assert_json_field "$LOG" -1 tables.django_migrations 3
assert_json_field "$LOG" -1 tables.core_user 2
assert_json_field "$LOG" -1 tables.billing_invoice 1
assert_json_field "$LOG" -1 missing_tables.0 patients_patient
leftover="$(sql postgres "SELECT count(*) FROM pg_database WHERE datname LIKE 'restore_test_%'")"
assert_eq "$leftover" "0" "scratch database dropped"
pass "restore test restores the newest dump, counts rows, logs JSON and drops the scratch DB"

# A scratch database left by a killed run is dropped by the next restore test.
sql postgres "CREATE DATABASE \"restore_test_20200101000000_1\""
"$BK/restore-test.sh" 2>"$WORK/r0.err" || { cat "$WORK/r0.err" >&2; fail "restore-test after a crash"; }
leftover="$(sql postgres "SELECT count(*) FROM pg_database WHERE datname LIKE 'restore_test_%'")"
assert_eq "$leftover" "0" "leftover scratch database dropped"
pass "restore test drops scratch databases left by a killed run"

# ---------------------------------------------------------------- 4. restore test failure modes
cp "$dump1" "$WORK/tampered.dump"
printf '%s  tampered.dump\n' "0000000000000000000000000000000000000000000000000000000000000000" >"$WORK/tampered.dump.sha256"
if "$BK/restore-test.sh" --dump "$WORK/tampered.dump" 2>/dev/null; then fail "checksum mismatch must fail"; fi
assert_json_field "$LOG" -1 status failed
assert_json_contains "$LOG" -1 error "checksum mismatch"

if RESTORE_TEST_REQUIRED="empty_table" "$BK/restore-test.sh" --dump "$dump1" 2>/dev/null; then
  fail "an empty required table must fail"
fi
assert_json_contains "$LOG" -1 error "empty_table is empty"

printf 'not a dump' >"$WORK/garbage.dump"
if "$BK/restore-test.sh" --dump "$WORK/garbage.dump" 2>/dev/null; then fail "garbage dump must fail"; fi
assert_json_contains "$LOG" -1 error "pg_restore failed"
leftover="$(sql postgres "SELECT count(*) FROM pg_database WHERE datname LIKE 'restore_test_%'")"
assert_eq "$leftover" "0" "scratch databases dropped after failures"
pass "restore test fails on bad checksum, empty required table and unreadable dump"

# ---------------------------------------------------------------- 5. backup failure is recorded
if DB_NAME="infra_test_missing_$ID" "$BK/backup-nightly.sh" >/dev/null 2>&1; then
  fail "backup of a missing database must fail"
fi
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 status failed
assert_json_contains "$BACKUP_DIR/status/backup-runs.jsonl" -1 error "cannot connect"
# A live holder (another container, another process) blocks the run, and the refusal is recorded.
hold_lock() {
  perl -MFcntl=:flock -e 'open(my $f, ">>", $ARGV[0]) or die; flock($f, LOCK_EX) or die;
    open(my $r, ">", $ARGV[1]) or die; close $r; sleep 60' "$1" "$WORK/held" &
  holder=$!
  for _ in $(seq 1 50); do [[ -f "$WORK/held" ]] && return 0; sleep 0.1; done
  fail "could not take the test lock"
}
hold_lock "$BACKUP_DIR/.backup.flock"
if DB_NAME="$SRC" "$BK/backup-nightly.sh" >/dev/null 2>"$WORK/lock.err"; then fail "lock must block"; fi
grep -q "another backup run holds" "$WORK/lock.err" || fail "lock message"
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 status failed
assert_json_contains "$BACKUP_DIR/status/backup-runs.jsonl" -1 error "another backup run holds"
kill "$holder" && wait "$holder" 2>/dev/null || true
rm -f "$WORK/held"
# The holder died: the kernel released the lock. A lock file that names a dead or recycled
# PID (even this run's own PID, as in a fresh container) must never block.
printf 'pid=%s host=%s since=x\n' "$$" "$(hostname)" >"$BACKUP_DIR/.backup.flock"
printf 'half a dump' >"$BACKUP_DIR/dumps/.$SRC-20200101T000000Z.dump.partial"
DB_NAME="$SRC" "$BK/backup-nightly.sh" --no-prune >/dev/null 2>"$WORK/relock.err" || {
  cat "$WORK/relock.err" >&2
  fail "a lock left by a dead process must not block"
}
assert_eq "$(find "$BACKUP_DIR/dumps" -name '.*.partial' | wc -l | tr -d ' ')" "0" "leftover partial removed"
pass "failed and refused backups are recorded; a live lock blocks; dead holders never do; partials cleaned"

# ---------------------------------------------------------------- 5b. media failure keeps the dump
mkdir -p "$WORK/media-locked/private" && printf 'x' >"$WORK/media-locked/private/f"
chmod 000 "$WORK/media-locked/private"
set +e
partial_out="$(DB_NAME="$SRC" MEDIA_DIR="$WORK/media-locked" "$BK/backup-nightly.sh" --no-prune 2>"$WORK/media.err")"
partial_rc=$?
set -e
chmod 755 "$WORK/media-locked/private"
if [[ "$(id -u)" -eq 0 ]]; then
  echo "skip - media permission failure (root can read anything)"
else
  assert_eq "$partial_rc" "3" "media failure exits 3 (partial)"
  assert_file "$partial_out"
  assert_match "$partial_out" "\\.dump\$" "dump path still printed"
  assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 status partial
  assert_json_contains "$BACKUP_DIR/status/backup-runs.jsonl" -1 error "media archive failed"
  pass "an unreadable media directory gives status partial, exit 3, and keeps the verified dump"
fi

# ---------------------------------------------------------------- 6. restore-dump swaps safely
sql postgres "CREATE DATABASE \"$TGT\""
sql "$TGT" "CREATE TABLE marker (v text); INSERT INTO marker VALUES ('old');"
if "$BK/restore-dump.sh" --dump "$dump1" --target "$TGT" </dev/null >/dev/null 2>&1; then
  fail "restore-dump must refuse without --yes"
fi
"$BK/restore-dump.sh" --dump "$dump1" --target "$TGT" --yes >/dev/null 2>"$WORK/rd.err" || {
  cat "$WORK/rd.err" >&2
  fail "restore-dump failed"
}
assert_eq "$(sql "$TGT" "SELECT count(*) FROM core_user")" "2" "target now holds restored data"
before="$(sql postgres "SELECT datname FROM pg_database WHERE datname LIKE '${TGT}_before_%'")"
[[ -n "$before" ]] || fail "previous database must be kept"
assert_eq "$(sql "$before" "SELECT v FROM marker")" "old" "previous data intact under the _before_ name"
if sql "$TGT" "UPDATE billing_invoice SET total = 1" 2>/dev/null; then
  fail "restored immutability trigger must still block updates"
fi
pass "restore-dump restores beside the live DB, swaps names, keeps the old DB and triggers"

# ---------------------------------------------------------------- 7. manual backup requests
# The status page only inserts a row (apps.ops BackupRequest); backup-requests.sh picks it up.
sql "$SRC" "
CREATE TABLE ops_backuprequest (
  id bigserial PRIMARY KEY, requested_at timestamptz NOT NULL DEFAULT now(), note text NOT NULL DEFAULT '',
  status varchar(20) NOT NULL DEFAULT 'pending', started_at timestamptz, finished_at timestamptz,
  dump_file varchar(500) NOT NULL DEFAULT '', message text NOT NULL DEFAULT '');
"
dumps_before="$(find "$BACKUP_DIR/dumps" -name '*.dump' | wc -l | tr -d ' ')"
DB_NAME="$SRC" "$BK/backup-requests.sh" 2>"$WORK/req0.err" || { cat "$WORK/req0.err" >&2; fail "no request must be a no-op"; }
assert_eq "$(find "$BACKUP_DIR/dumps" -name '*.dump' | wc -l | tr -d ' ')" "$dumps_before" "no request, no dump"

req="$(sql "$SRC" "INSERT INTO ops_backuprequest DEFAULT VALUES RETURNING id")"
stale="$(sql "$SRC" "INSERT INTO ops_backuprequest (status, started_at) VALUES ('running', now() - interval '7 hours') RETURNING id")"
out="$(DB_NAME="$SRC" BACKUP_KEEP_MIN=50 "$BK/backup-requests.sh" 2>"$WORK/req1.err")" || {
  cat "$WORK/req1.err" >&2
  fail "backup-requests failed"
}
assert_eq "$out" "" "nothing on stdout"
assert_eq "$(sql "$SRC" "SELECT status FROM ops_backuprequest WHERE id = $req")" "succeeded" "request done"
req_dump="$(sql "$SRC" "SELECT dump_file FROM ops_backuprequest WHERE id = $req")"
assert_match "$req_dump" "-manual-$req\\.dump\$" "labelled manual dump recorded on the request"
assert_file "$req_dump"
assert_eq "$(sql "$SRC" "SELECT (started_at IS NOT NULL AND finished_at >= started_at)::text FROM ops_backuprequest WHERE id = $req")" "true" "times recorded"
assert_json_field "$BACKUP_DIR/status/backup-runs.jsonl" -1 label "manual-$req"
assert_eq "$(sql "$SRC" "SELECT status FROM ops_backuprequest WHERE id = $stale")" "failed" "interrupted request failed"
assert_json_contains "$BACKUP_DIR/status/backup-runs.jsonl" -1 status ok
pass "a pending manual backup request is claimed, backed up with its label and marked succeeded"

# A backup that cannot run (another run holds the lock) marks the request failed with the reason.
req2="$(sql "$SRC" "INSERT INTO ops_backuprequest DEFAULT VALUES RETURNING id")"
hold_lock "$BACKUP_DIR/.backup.flock"
DB_NAME="$SRC" "$BK/backup-requests.sh" 2>"$WORK/req2.err" || { cat "$WORK/req2.err" >&2; fail "a failed backup still exits 0"; }
kill "$holder" && wait "$holder" 2>/dev/null || true
rm -f "$WORK/held"
assert_eq "$(sql "$SRC" "SELECT status FROM ops_backuprequest WHERE id = $req2")" "failed" "failed request"
msg="$(sql "$SRC" "SELECT message FROM ops_backuprequest WHERE id = $req2")"
[[ "$msg" == *"another backup run holds"* ]] || fail "failure reason on the request: '$msg'"
# Only one request per run; the next one waits for the next poll.
r3="$(sql "$SRC" "INSERT INTO ops_backuprequest DEFAULT VALUES RETURNING id")"
r4="$(sql "$SRC" "INSERT INTO ops_backuprequest (status) VALUES ('succeeded') RETURNING id")"
DB_NAME="$SRC" BACKUP_KEEP_MIN=50 "$BK/backup-requests.sh" 2>/dev/null
assert_eq "$(sql "$SRC" "SELECT status FROM ops_backuprequest WHERE id = $r3")" "succeeded" "next request"
assert_eq "$(sql "$SRC" "SELECT finished_at IS NULL FROM ops_backuprequest WHERE id = $r4")" "t" "finished rows untouched"
pass "a refused backup marks its request failed with the reason; finished requests are left alone"

# A database migrated before manual backups existed has no table: nothing to do.
sql postgres "CREATE DATABASE \"infra_test_norequests_$ID\""
DB_NAME="infra_test_norequests_$ID" "$BK/backup-requests.sh" 2>"$WORK/req3.err" || { cat "$WORK/req3.err" >&2; fail "missing table must be a no-op"; }
if DB_NAME="infra_test_missing_$ID" "$BK/backup-requests.sh" 2>/dev/null; then fail "an unreachable database must fail"; fi
pass "no request table is a no-op; an unreachable database is an error"

summary
