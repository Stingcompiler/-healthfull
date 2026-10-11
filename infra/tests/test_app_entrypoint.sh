#!/usr/bin/env bash
# The app image's maintenance cycle (infra/docker/app-entrypoint.sh): sessions, time-based
# alerts, the daily integrity check and the nightly bed charge as BED_CHARGE_USER. A fake `python` on PATH records the
# management commands instead of running Django.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ENTRY="$(cd "$HERE/../docker" && pwd -P)/app-entrypoint.sh"
# shellcheck source=infra/tests/testlib.sh
source "$HERE/testlib.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-entrypoint-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
cat >"$WORK/bin/python" <<'SH'
#!/usr/bin/env bash
# `python -` is the entrypoint's wait-for-database probe: succeed at once.
if [[ "${1:-}" == "-" ]]; then cat >/dev/null; exit 0; fi
printf '%s\n' "$*" >>"$FAKE_PYTHON_LOG"
case " $* " in *" ${FAKE_PYTHON_FAIL:-none} "*) exit 1 ;; esac
exit 0
SH
chmod +x "$WORK/bin/python"
export PATH="$WORK/bin:$PATH"
export FAKE_PYTHON_LOG="$WORK/calls.log"

run_once() {
  : >"$FAKE_PYTHON_LOG"
  (cd "$WORK" && bash "$ENTRY" maintenance-once >"$WORK/out.log" 2>"$WORK/err.log")
}

BED_CHARGE_USER=bedbot run_once || fail "maintenance-once failed"
assert_eq "$(cat "$FAKE_PYTHON_LOG")" "manage.py maintenance
manage.py notify_scan
manage.py integrity_check --daily
manage.py charge_bed_nights --as bedbot" "one cycle runs the four jobs in order"
pass "a maintenance cycle cleans up, raises alerts, checks integrity daily and charges bed nights as BED_CHARGE_USER"

BED_CHARGE_USER="" run_once || fail "maintenance-once without a bed user failed"
assert_eq "$(cat "$FAKE_PYTHON_LOG")" "manage.py maintenance
manage.py notify_scan
manage.py integrity_check --daily" "no bed charge without a user"
grep -q "BED_CHARGE_USER is not set" "$WORK/out.log" || fail "the skipped bed charge is logged"
pass "without BED_CHARGE_USER the bed charge is skipped and says so"

FAKE_PYTHON_FAIL=notify_scan BED_CHARGE_USER=bedbot run_once || fail "a failing job must not stop the cycle"
grep -q "charge_bed_nights --as bedbot" "$FAKE_PYTHON_LOG" || fail "later jobs still run"
grep -q "notify_scan failed; retrying next cycle" "$WORK/err.log" || fail "the failure is logged"
pass "a failing job is logged and the others still run"

FAKE_PYTHON_FAIL=--daily BED_CHARGE_USER=bedbot run_once || fail "a failing integrity job must not stop the cycle"
grep -q "charge_bed_nights --as bedbot" "$FAKE_PYTHON_LOG" || fail "the bed charge still runs"
grep -q "integrity_check failed; retrying next cycle" "$WORK/err.log" || fail "the failure is logged"
pass "an integrity check that cannot run is logged and the cycle goes on"

for bad in abc 0 -5; do
  if (cd "$WORK" && MAINTENANCE_INTERVAL_SECONDS="$bad" bash "$ENTRY" maintenance-loop >/dev/null 2>&1); then
    fail "interval '$bad' must be refused"
  fi
done
pass "a zero or non-numeric MAINTENANCE_INTERVAL_SECONDS is refused"

summary
