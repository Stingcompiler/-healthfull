#!/usr/bin/env bash
# Tests for render-pgbackrest-conf.sh (template rendering) and scheduler.sh (slot arithmetic).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BK="$(cd "$HERE/../backup" && pwd -P)"
# shellcheck source=infra/tests/testlib.sh
source "$HERE/testlib.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-conf-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

render() { env -i PATH="$PATH" HOME="$HOME" "$@" "$BK/render-pgbackrest-conf.sh" "$WORK/out.conf" 2>"$WORK/err"; }

# ---------------------------------------------------------------- local-only default
render
grep -q '^repo1-path=/var/lib/pgbackrest$' "$WORK/out.conf" || fail "repo1 path"
grep -q '^\[hospital\]$' "$WORK/out.conf" || fail "stanza section"
grep -q '^pg1-user=postgres$' "$WORK/out.conf" || fail "pg1-user default"
grep -q '^repo2' "$WORK/out.conf" && fail "repo2 must be absent without a bucket"
grep -q '^repo1-cipher' "$WORK/out.conf" && fail "repo1 cipher absent without a passphrase"
grep -v '^#' "$WORK/out.conf" | grep -q '\${' && fail "unrendered placeholder"
mode="$(stat -c %a "$WORK/out.conf" 2>/dev/null || stat -f %Lp "$WORK/out.conf")"
assert_eq "$mode" "640" "secrets file mode"
pass "default render: local repo only, no secrets, mode 0640"

# ---------------------------------------------------------------- repo2 needs everything
if render PGBACKREST_REPO2_S3_BUCKET=b PGBACKREST_REPO2_S3_ENDPOINT=e PGBACKREST_REPO2_S3_REGION=r \
  PGBACKREST_REPO2_S3_KEY=k PGBACKREST_REPO2_S3_KEY_SECRET=s; then
  fail "repo2 without an encryption passphrase must be refused"
fi
grep -q "PGBACKREST_REPO2_CIPHER_PASS is required" "$WORK/err" || fail "missing passphrase message"
if render PGBACKREST_REPO2_S3_BUCKET=b PGBACKREST_REPO2_S3_ENDPOINT=e PGBACKREST_REPO2_S3_REGION=r \
  PGBACKREST_REPO2_S3_KEY=k PGBACKREST_REPO2_S3_KEY_SECRET=s PGBACKREST_REPO2_CIPHER_PASS=short; then
  fail "short passphrase must be refused"
fi
pass "cloud repo refused unless fully configured with a strong passphrase"

# ---------------------------------------------------------------- repo2 complete, literal secrets
render PGBACKREST_STANZA=clinic POSTGRES_USER=hospital \
  PGBACKREST_REPO1_CIPHER_PASS='a&b\c$d${NOT_EXPANDED}' \
  PGBACKREST_REPO2_S3_BUCKET=clinic-backups PGBACKREST_REPO2_S3_ENDPOINT=s3.example.net \
  PGBACKREST_REPO2_S3_REGION=af-south-1 PGBACKREST_REPO2_S3_KEY=AKIAEXAMPLE \
  PGBACKREST_REPO2_S3_KEY_SECRET='s3cr&t/+=' PGBACKREST_REPO2_CIPHER_PASS='correct-horse-battery-staple' ||
  { cat "$WORK/err"; fail "full render failed"; }
grep -qF 'repo1-cipher-pass=a&b\c$d${NOT_EXPANDED}' "$WORK/out.conf" || fail "secret must be copied literally"
grep -qF 'repo2-s3-key-secret=s3cr&t/+=' "$WORK/out.conf" || fail "S3 secret literal"
grep -q '^repo2-cipher-type=aes-256-cbc$' "$WORK/out.conf" || fail "repo2 encrypted"
grep -q '^\[clinic\]$' "$WORK/out.conf" || fail "custom stanza"
grep -q '^pg1-user=hospital$' "$WORK/out.conf" || fail "pg1-user from POSTGRES_USER"
pass "cloud repo rendered encrypted; secrets copied literally (&, \\, \$, \${...})"

# ---------------------------------------------------------------- template safety
printf '[global]\nrepo1-path=${HOME}\n' >"$WORK/evil.template"
if env -i PATH="$PATH" HOME=/root "$BK/render-pgbackrest-conf.sh" "$WORK/x.conf" "$WORK/evil.template" 2>/dev/null; then
  fail "non-whitelisted placeholder must be refused"
fi
if render PGBACKREST_STANZA='bad name'; then fail "invalid stanza must be refused"; fi
pass "only whitelisted placeholders; invalid values refused"

# ---------------------------------------------------------------- scheduler slot arithmetic
assert_eq "$("$BK/scheduler.sh" --next 9000 14400 3600)" "backup 5400" "before backup"
assert_eq "$("$BK/scheduler.sh" --next 9000 14400 10000)" "restore 4400" "between slots"
assert_eq "$("$BK/scheduler.sh" --next 9000 14400 80000)" "backup 15400" "wraps past midnight"
assert_eq "$("$BK/scheduler.sh" --next 9000 14400 9000)" "restore 5400" "slot that just fired is next day"
if BACKUP_TIME=24:00 "$BK/scheduler.sh" 2>/dev/null; then fail "invalid time must be refused"; fi
if RESTORE_TEST_DAY=31 "$BK/scheduler.sh" 2>/dev/null; then fail "day 31 must be refused"; fi
pass "scheduler picks the next slot and validates its settings"

summary
