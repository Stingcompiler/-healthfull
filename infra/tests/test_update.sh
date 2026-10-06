#!/usr/bin/env bash
# Control-flow tests for infra/update.sh against a fake docker (infra/tests/fake-docker/docker).
# Verifies ordering (backup before migrate before swap), the env file only changing on success,
# rollback to the previous tag, and the database restore happening only with the explicit flag.
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
  printf 'IMAGE_REGISTRY=hospital-sys\nAPP_IMAGE_TAG=v1.0.0\nBACKUP_HOST_DIR=%s\nPOSTGRES_PASSWORD=x\n' \
    "$WORK/case/backups" >"$ENV_FILE"
  echo "v1.0.0" >"$FAKE_STATE/running"
  unset FAKE_PENDING FAKE_HEALTH_v2_0_0 FAKE_HEALTH_v1_0_0 FAKE_BACKUP_EXIT FAKE_MIGRATE_EXIT \
    FAKE_PULL_EXIT FAKE_MISSING_IMAGE FAKE_RESTORE_EXIT FAKE_UP_EXIT || true
}

run_update() {
  set +e
  "$UPDATE" --tag v2.0.0 --yes --health-retries 2 --health-interval 0 "$@" >"$WORK/case/out.log" 2>&1
  CODE=$?
  set -e
}

calls() { cat "$FAKE_STATE/calls.log"; }
called() { grep -q -- "$1" "$FAKE_STATE/calls.log"; }
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
m=$(line_of "TAG=v2.0.0 compose run --rm --no-deps -T app migrate$")
u=$(line_of "TAG=v2.0.0 compose up -d --no-deps app web")
p=$(line_of "app manage migrate --plan")
[[ -n "$p" && -n "$s" && -n "$b" && -n "$m" && -n "$u" ]] || show_and_fail "missing a step"
[[ $p -lt $s && $s -lt $b && $b -lt $m && $m -lt $u ]] || show_and_fail "steps out of order"
called "compose pull app web" || show_and_fail "images not pulled"
ls "$UPDATE_LOG_DIR"/update-*-v2.0.0.log >/dev/null 2>&1 || show_and_fail "update log file written"
pass "success: plan, stop, backup, migrate, swap, health, commit (in that order)"

# ---------------------------------------------------------------- success without migrations
setup
run_update
[[ $CODE -eq 0 ]] || show_and_fail "expected success, got $CODE"
called "compose stop app" && show_and_fail "app must keep serving when nothing is migrated"
called "app migrate$" && show_and_fail "migrate must not run without pending migrations"
called "backup-nightly.sh" || show_and_fail "backup must still run"
pass "success without pending migrations: no maintenance stop, no migrate"

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
called "app migrate$" && show_and_fail "must not migrate without a backup"
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

[[ ! -d "$(cd "$HERE/.." && pwd -P)/.update.lock" ]] || fail "lock released"

summary
