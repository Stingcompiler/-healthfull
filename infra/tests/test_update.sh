#!/usr/bin/env bash
# Control-flow tests for infra/update.sh against a fake docker (infra/tests/fake-docker/docker).
# Verifies ordering (backup before roles before migrate before swap), the env file only changing
# on success, rollback to the previous tag, the database restore happening only with the
# explicit flag, migrations running in the owner-role `migrate` service, and the role passwords
# never appearing on a docker command line.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
UPDATE="$(cd "$HERE/.." && pwd -P)/update.sh"
# shellcheck source=infra/tests/testlib.sh
source "$HERE/testlib.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-update-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
export PATH="$HERE/fake-docker:$PATH"

setup() {
  rm -rf "$WORK/case"
  mkdir -p "$WORK/case/state" "$WORK/case/logs" "$WORK/case/backups/status"
  export FAKE_STATE="$WORK/case/state"
  export ENV_FILE="$WORK/case/.env"
  export UPDATE_LOG_DIR="$WORK/case/logs"
  export UPDATE_STATE_DIR="$WORK/case/state-dir"
  printf 'IMAGE_REGISTRY=hospital-sys\nAPP_IMAGE_TAG=v1.0.0\nBACKUP_HOST_DIR=%s\nPOSTGRES_PASSWORD=x\n' \
    "$WORK/case/backups" >"$ENV_FILE"
  printf 'DB_OWNER_PASSWORD=%s\nDB_APP_PASSWORD=%s\n' "$OWNER_PW" "$APP_PW" >>"$ENV_FILE"
  echo "v1.0.0" >"$FAKE_STATE/running"
  unset FAKE_PENDING FAKE_HEALTH_v2_0_0 FAKE_HEALTH_v1_0_0 FAKE_BACKUP_EXIT FAKE_MIGRATE_EXIT \
    FAKE_PULL_EXIT FAKE_MISSING_IMAGE FAKE_RESTORE_EXIT FAKE_UP_EXIT FAKE_ROLES_EXIT \
    FAKE_VERIFY_OUTPUT || true
}
OWNER_PW="owner-test-value-0123456789"
APP_PW="app-test-value-0123456789"

run_update() {
  set +e
  "$UPDATE" --tag v2.0.0 --yes --health-retries 2 --health-interval 0 "$@" >"$WORK/case/out.log" 2>&1
  CODE=$?
  set -e
}

calls() { cat "$FAKE_STATE/calls.log"; }
called() { grep -qs -- "$1" "$FAKE_STATE/calls.log"; }
line_of() { grep -n -- "$1" "$FAKE_STATE/calls.log" | head -n 1 | cut -d: -f1 || true; }
env_tag() { grep '^APP_IMAGE_TAG=' "$ENV_FILE" | cut -d= -f2; }
last_status() { _json_get "$WORK/case/backups/status/update-runs.jsonl" -1 status; }

show_and_fail() {
  echo "--- calls"; calls; echo "--- output"; cat "$WORK/case/out.log"
  fail "$1"
}

# ---------------------------------------------------------------- success with migrations
setup
export FAKE_PENDING=1
run_update
[[ $CODE -eq 0 ]] || show_and_fail "expected success, got exit $CODE"
assert_eq "$(env_tag)" "v2.0.0" "env file committed to the new tag"
assert_eq "$(last_status)" "ok" "update recorded"
b=$(line_of "backup-nightly.sh --label pre-update-v2.0.0")
s=$(line_of "compose stop app")
r=$(line_of "compose exec -T db sh -c")
m=$(line_of "TAG=v2.0.0 compose run --rm --no-deps -T migrate migrate$")
u=$(line_of "TAG=v2.0.0 compose up -d --no-deps app web")
p=$(line_of "TAG=v2.0.0 compose run --rm --no-deps -T migrate manage migrate --plan")
c=$(line_of "TAG=v2.0.0 compose run --rm --no-deps -T app manage check")
[[ -n "$c" && -n "$p" && -n "$s" && -n "$b" && -n "$r" && -n "$m" && -n "$u" ]] || show_and_fail "missing a step"
[[ $c -lt $s && $p -lt $s && $s -lt $b && $b -lt $r && $r -lt $m && $m -lt $u ]] || show_and_fail "steps out of order"
called "compose pull app web" || show_and_fail "images not pulled"
called "app migrate$" && show_and_fail "the app service (app role) must never run migrations"
ls "$UPDATE_LOG_DIR"/update-*-v2.0.0.log >/dev/null 2>&1 || show_and_fail "update log file written"
pass "success: check, plan, stop, backup, roles, migrate (owner role), swap, health, commit (in order)"

grep -q "^\\\\set app_role 'hospital_app'$" "$FAKE_STATE/roles-apply.sql" || show_and_fail "roles SQL not sent on stdin"
grep -q "^\\\\set app_pw '$APP_PW'$" "$FAKE_STATE/roles-apply.sql" || show_and_fail "app password not set from .env"
grep -q "ALTER DEFAULT PRIVILEGES" "$FAKE_STATE/roles-apply.sql" || show_and_fail "roles.sql body not sent"
[[ -f "$FAKE_STATE/roles-verify.sql" ]] || show_and_fail "roles not verified"
grep -qs -e "$APP_PW" -e "$OWNER_PW" "$FAKE_STATE/calls.log" && show_and_fail "a role password reached a docker command line"
pass "roles: applied and verified through psql stdin; passwords never on a command line"

# ---------------------------------------------------------------- success without migrations
setup
run_update
[[ $CODE -eq 0 ]] || show_and_fail "expected success, got $CODE"
called "compose stop app" && show_and_fail "app must keep serving when nothing is migrated"
called "migrate migrate$" && show_and_fail "migrate must not run without pending migrations"
called "backup-nightly.sh" || show_and_fail "backup must still run"
called "compose exec -T db sh -c" || show_and_fail "roles are checked on every update"
pass "success without pending migrations: no maintenance stop, no migrate, roles still checked"

# ---------------------------------------------------------------- health fails, migrated, no flag
setup
export FAKE_PENDING=1 FAKE_HEALTH_v2_0_0=degraded
run_update
assert_eq "$CODE" "1" "exit code after rollback"
assert_eq "$(env_tag)" "v1.0.0" "env file unchanged on failure"
called "TAG=v1.0.0 compose up -d --no-deps app web" || show_and_fail "no rollback to previous tag"
called "restore-dump.sh" && show_and_fail "DB restore must need --restore-db-on-failure"
grep -q "restore-dump.sh --dump /backups/dumps/" "$WORK/case/out.log" || show_and_fail "manual restore hint missing"
assert_eq "$(last_status)" "rolled_back" "rollback recorded"
assert_eq "$(_json_get "$WORK/case/backups/status/update-runs.jsonl" -1 migrations_applied)" "True" "migrations flagged"
assert_eq "$(_json_get "$WORK/case/backups/status/update-runs.jsonl" -1 db_restored)" "False" "no restore"
assert_json_contains "$WORK/case/backups/status/update-runs.jsonl" -1 detail "during 6/7 health check"
pass "unhealthy new version: rolls back app, keeps DB, prints the restore command"

# ---------------------------------------------------------------- health fails, migrated, flag
setup
export FAKE_PENDING=1 FAKE_HEALTH_v2_0_0=degraded
run_update --restore-db-on-failure
assert_eq "$CODE" "1" "exit code after rollback with restore"
r=$(line_of "restore-dump.sh --dump /backups/dumps/hospital-20261006T000000Z-pre-update.dump --yes")
u=$(line_of "TAG=v1.0.0 compose up -d --no-deps app web")
[[ -n "$r" && -n "$u" && $r -lt $u ]] || show_and_fail "restore must happen before restarting the old tag"
assert_eq "$(_json_get "$WORK/case/backups/status/update-runs.jsonl" -1 db_restored)" "True" "restore recorded"
pass "unhealthy new version with --restore-db-on-failure: restores the pre-update dump, then old tag"

# ---------------------------------------------------------------- flag but nothing migrated
setup
export FAKE_HEALTH_v2_0_0=degraded
run_update --restore-db-on-failure
assert_eq "$CODE" "1" "exit"
called "restore-dump.sh" && show_and_fail "no migration applied: the DB must not be restored"
called "TAG=v1.0.0 compose up -d --no-deps app web" || show_and_fail "rollback missing"
pass "restore never happens when no migration was applied, even with the flag"

# ---------------------------------------------------------------- backup fails
setup
export FAKE_PENDING=1 FAKE_BACKUP_EXIT=1
run_update --restore-db-on-failure
assert_eq "$CODE" "1" "exit"
called "migrate migrate$" && show_and_fail "must not migrate without a backup"
called "compose exec -T db" && show_and_fail "must not touch roles without a backup"
called "TAG=v2.0.0 compose up" && show_and_fail "must not swap without a backup"
called "TAG=v1.0.0 compose up -d --no-deps app web" || show_and_fail "stopped app must be restarted"
assert_eq "$(env_tag)" "v1.0.0" "env unchanged"
pass "failed backup aborts before migrating and restarts the stopped app"

# ---------------------------------------------------------------- migration fails
setup
export FAKE_PENDING=1 FAKE_MIGRATE_EXIT=1
run_update --restore-db-on-failure
assert_eq "$CODE" "1" "exit"
called "TAG=v2.0.0 compose up" && show_and_fail "must not swap after failed migrations"
called "restore-dump.sh" || show_and_fail "partly applied migrations must be restorable"
pass "failed migration: no swap, restore with the flag, previous tag restarted"

# ---------------------------------------------------------------- roles cannot be applied
setup
export FAKE_PENDING=1 FAKE_ROLES_EXIT=3
run_update --restore-db-on-failure
assert_eq "$CODE" "1" "exit"
called "migrate migrate$" && show_and_fail "must not migrate when the roles could not be applied"
called "TAG=v2.0.0 compose up" && show_and_fail "must not swap when the roles could not be applied"
called "restore-dump.sh" && show_and_fail "nothing migrated: no restore"
called "TAG=v1.0.0 compose up -d --no-deps app web" || show_and_fail "stopped app must be restarted"
assert_eq "$(env_tag)" "v1.0.0" "env unchanged"
assert_json_contains "$WORK/case/backups/status/update-runs.jsonl" -1 detail "database roles"
pass "roles that cannot be applied stop the update before migrating; the old tag serves again"

setup
export FAKE_VERIFY_OUTPUT="PROBLEM: hospital owns public.billing_invoice"
run_update
assert_eq "$CODE" "1" "exit"
called "TAG=v2.0.0 compose up" && show_and_fail "must not swap when verification finds problems"
grep -q "PROBLEM: hospital owns public.billing_invoice" "$WORK/case/out.log" || show_and_fail "problem printed"
pass "a role verification problem stops the update and is printed"

# ---------------------------------------------------------------- install without role passwords
setup
grep -v '^DB_\(OWNER\|APP\)_PASSWORD=' "$ENV_FILE" >"$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
run_update
assert_eq "$CODE" "2" "missing role passwords is a usage error"
[[ -f "$FAKE_STATE/calls.log" ]] && show_and_fail "no docker call without role passwords"
grep -q "infra/db-roles.sh" "$WORK/case/out.log" || show_and_fail "points the operator to infra/db-roles.sh"
pass "an install without role passwords is refused before any docker call, with the fix named"

# ---------------------------------------------------------------- rollback itself unhealthy
setup
export FAKE_HEALTH_v2_0_0=degraded FAKE_HEALTH_v1_0_0=degraded
run_update
assert_eq "$CODE" "3" "exit 3 when the rollback is unhealthy too"
grep -q "NOT healthy" "$WORK/case/out.log" || show_and_fail "loud rollback failure message"
pass "unhealthy rollback exits 3 with an operator alert"

# ---------------------------------------------------------------- dry run, archive, preflight
setup
export FAKE_PENDING=1
run_update --dry-run
assert_eq "$CODE" "0" "dry run exit"
called "migrate --plan" || show_and_fail "dry run must show the plan"
called "backup-nightly.sh" && show_and_fail "dry run must not back up"
called "compose up" && show_and_fail "dry run must not swap"
called "compose stop" && show_and_fail "dry run must not stop the app"
called "compose exec -T db" && show_and_fail "dry run must not touch the database roles"
pass "dry run: pull and migration plan only"

setup
printf 'fake' >"$WORK/case/images.tar"
run_update --image-archive "$WORK/case/images.tar"
assert_eq "$CODE" "0" "archive update"
called "load -i $WORK/case/images.tar" || show_and_fail "docker load not used"
called "compose pull" && show_and_fail "must not pull when loading an archive"
pass "offline update from an image archive"

setup
export FAKE_MISSING_IMAGE="web:v2.0.0"
run_update
assert_eq "$CODE" "1" "missing image"
called "backup-nightly.sh" && show_and_fail "must stop before backup when an image is missing"
grep -q "nothing was changed" "$WORK/case/out.log" || show_and_fail "nothing-changed message"
pass "missing image: stops before touching anything"

setup
set +e
"$UPDATE" --tag 'bad tag;rm' --yes >"$WORK/case/out.log" 2>&1
code=$?
set -e
assert_eq "$code" "2" "invalid tag is a usage error"
[[ -f "$FAKE_STATE/calls.log" ]] && show_and_fail "no docker call on usage error"
pass "invalid tag rejected before any docker call"

# ---------------------------------------------------------------- partial pre-update backup
setup
export FAKE_PENDING=1 FAKE_BACKUP_EXIT=3
run_update
[[ $CODE -eq 0 ]] || show_and_fail "a partial backup (verified dump) must not block the update"
grep -q "PARTIAL" "$WORK/case/out.log" || show_and_fail "partial backup warning missing"
assert_eq "$(env_tag)" "v2.0.0" "updated"
pass "partial pre-update backup (dump ok, media failed): update continues with a warning"

# ---------------------------------------------------------------- crash safety
setup
chmod 600 "$ENV_FILE"
run_update
[[ $CODE -eq 0 ]] || show_and_fail "expected success"
assert_eq "$(stat -c %a "$ENV_FILE" 2>/dev/null || stat -f %Lp "$ENV_FILE")" "600" ".env keeps its mode"
[[ -z "$(find "$(dirname "$ENV_FILE")" -maxdepth 1 -name '.env.update.*')" ]] || show_and_fail "temp env file left"
grep -q '^POSTGRES_PASSWORD=x$' "$ENV_FILE" || show_and_fail "other settings kept"
[[ ! -f "$UPDATE_STATE_DIR/.update.state" ]] || show_and_fail "state file removed after success"
pass ".env is replaced atomically with its mode kept; no state left after success"

setup
mkdir -p "$UPDATE_STATE_DIR"
printf 'target=v2.0.0\nfrom=v1.0.0\nstep=5/7 swap app and web to v2.0.0\nmigrated=1\nswapped=1\ndump=/backups/dumps/x.dump\n' \
  >"$UPDATE_STATE_DIR/.update.state"
# A lock file naming a dead process (as after a power cut) must not block either.
printf 'pid=999999 host=gone since=x\n' >"$UPDATE_STATE_DIR/.update.flock"
run_update
[[ $CODE -eq 0 ]] || show_and_fail "rerun after an interrupted update must work"
grep -q "previous update to v2.0.0 was interrupted during '5/7 swap" "$WORK/case/out.log" ||
  show_and_fail "interrupted update not reported"
[[ ! -f "$UPDATE_STATE_DIR/.update.state" ]] || show_and_fail "state cleared once finished"
pass "an interrupted update is detected and finished by the next run; stale lock files never block"

setup
mkdir -p "$UPDATE_STATE_DIR"
perl -MFcntl=:flock -e 'open(my $f, ">>", $ARGV[0]) or die; flock($f, LOCK_EX) or die;
  open(my $r, ">", $ARGV[1]) or die; close $r; sleep 30' "$UPDATE_STATE_DIR/.update.flock" "$WORK/held" &
holder=$!
for _ in $(seq 1 50); do [[ -f "$WORK/held" ]] && break; sleep 0.1; done
run_update
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null || true
rm -f "$WORK/held"
assert_eq "$CODE" "1" "a running update blocks a second one"
grep -q "another update is running" "$WORK/case/out.log" || show_and_fail "lock message"
called "compose pull" && show_and_fail "blocked run must not touch anything"
pass "a live update holds the lock; a second run refuses"

summary
