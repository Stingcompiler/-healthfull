#!/usr/bin/env bash
# Update hospital-sys to a new image tag with a safety net (FEATURES 13.10, STACK.md).
#
#   1. get images      pull <registry>/app:TAG and web:TAG (or `docker load` an offline archive)
#   2. preflight       Django system checks and `migrate --plan` (dry run, as the owner role)
#                      in one-off containers of the NEW image
#   3. backup          verified pg_dump labelled pre-update-TAG (infra/backup/backup-nightly.sh);
#                      with pending migrations the app is stopped first, so no write made after
#                      the backup can be lost by a restore (the SPA stays up and shows errors)
#   4. migrate         database roles checked and repaired (infra/db-roles.sh), then `migrate`
#                      in a one-off `migrate` container of the NEW image, which connects as the
#                      owner role (only when migrations are pending). The app role never can.
#   5. swap            recreate app and web on the new tag
#   6. health          GET /api/ops/health inside the app until status=ok and version=TAG
#   7. commit          write APP_IMAGE_TAG=TAG to .env, record the run
# On failure after step 3: restart the PREVIOUS tag. The database is restored from the step-3 dump
# only when migrations were applied AND the operator passed --restore-db-on-failure.
#
# Usage: infra/update.sh --tag TAG [--image-archive FILE] [--restore-db-on-failure] [--yes]
#                        [--dry-run] [--health-retries N] [--health-interval SECONDS]
#
# Settings (shell environment first, then the env file): ENV_FILE [<repo>/.env],
#   UPDATE_LOG_DIR [<repo>/infra/logs], UPDATE_STATE_DIR [<repo>/infra] (lock and state file),
#   UPDATE_HEALTH_URL [] optional extra URL checked from the host, e.g.
#   http://127.0.0.1/api/ops/health (needs curl on the host)
#
# Crash safety (power cuts): the lock is a flock(2) the kernel drops when this process dies;
# .env is replaced atomically (temp file + rename); a state file records the target tag and
# the current step, so the next run says what an interrupted update left behind.
#
# Exit codes: 0 updated; 1 failed and rolled back (or nothing changed); 2 usage error;
#             3 failed AND the rollback itself is unhealthy: act now (docs/runbooks/update-rollback.md).
set -euo pipefail
shopt -u patsub_replacement 2>/dev/null || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
COMPOSE_FILE="$ROOT/infra/docker-compose.yml"
STATE_DIR="${UPDATE_STATE_DIR:-$ROOT/infra}"

NEW_TAG=""
ARCHIVE=""
RESTORE_DB=0
ASSUME_YES=0
DRY_RUN=0
HEALTH_RETRIES=30
HEALTH_INTERVAL=5

usage() {
  sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) NEW_TAG="${2:-}"; shift 2 ;;
    --image-archive) ARCHIVE="${2:-}"; shift 2 ;;
    --restore-db-on-failure) RESTORE_DB=1; shift ;;
    --yes | -y) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --health-retries) HEALTH_RETRIES="${2:-}"; shift 2 ;;
    --health-interval) HEALTH_INTERVAL="${2:-}"; shift 2 ;;
    -h | --help) usage ;;
    *) echo "update: unknown argument $1" >&2; usage ;;
  esac
done

[[ "$NEW_TAG" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || { echo "update: --tag is required (letters, digits, . _ -)" >&2; exit 2; }
[[ "$HEALTH_RETRIES" =~ ^[1-9][0-9]*$ && "$HEALTH_INTERVAL" =~ ^[0-9]+$ ]] || { echo "update: bad health retry settings" >&2; exit 2; }
[[ -z "$ARCHIVE" || -f "$ARCHIVE" ]] || { echo "update: image archive not found: $ARCHIVE" >&2; exit 2; }
[[ -f "$ENV_FILE" ]] || { echo "update: $ENV_FILE not found" >&2; exit 2; }
# Absolute and exported: docker-compose.yml passes the same file to every container.
ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd -P)/$(basename "$ENV_FILE")"
export ENV_FILE

# ------------------------------------------------------------------------------------ settings
# env_get KEY (last value in the env file) and env_set KEY VALUE (atomic replace).
# shellcheck source=infra/env-lib.sh
source "$ROOT/infra/env-lib.sh"

# The shell environment wins; otherwise the value from the env file; otherwise the default.
LOG_DIR="${UPDATE_LOG_DIR:-$(env_get UPDATE_LOG_DIR)}"
LOG_DIR="${LOG_DIR:-$ROOT/infra/logs}"
UPDATE_HEALTH_URL="${UPDATE_HEALTH_URL:-$(env_get UPDATE_HEALTH_URL)}"

# Installs made before the owner/app role split have no role passwords yet; every compose
# command below would refuse to start. Say what to do instead of failing on the first pull.
for key in DB_OWNER_PASSWORD DB_APP_PASSWORD; do
  if [[ -z "${!key:-}" && -z "$(env_get "$key")" ]]; then
    echo "update: $key is not set in $ENV_FILE. This install predates the separate database" >&2
    echo "update: roles: run infra/db-roles.sh, then infra/compose.sh up -d, then this update" >&2
    echo "update: (docs/runbooks/update-rollback.md, \"Separate database roles\")." >&2
    exit 2
  fi
done

# ------------------------------------------------------------------------------------ logging
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/update-$STAMP-$NEW_TAG.log"
exec > >(tee -a "$LOG_FILE") 2>&1

STEP=""
log() { printf '%s [update] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
step() {
  STEP="$1"
  log "==> $1"
  [[ "${LOCKED:-0}" -eq 1 ]] && save_state
  return 0
}
warn() { log "WARNING: $*"; }

# ------------------------------------------------------------------------------------ helpers
compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

compose_tag() {
  # compose with APP_IMAGE_TAG overridden for this call only (shell env beats --env-file).
  local tag="$1"
  shift
  APP_IMAGE_TAG="$tag" compose "$@"
}

HEALTH_PY='import json, sys, urllib.request, urllib.error
try:
    body = urllib.request.urlopen("http://127.0.0.1:8000/api/ops/health", timeout=5).read()
except urllib.error.HTTPError as exc:
    body = exc.read()
except Exception:
    print("unreachable -"); sys.exit(0)
try:
    data = json.loads(body)
except ValueError:
    print("invalid -"); sys.exit(0)
print(data.get("status", "unknown"), data.get("version", "-"))'

check_health() {
  # check_health TAG: wait until the app reports status=ok and version=TAG.
  local tag="$1" i out status version
  for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    out="$(compose_tag "$tag" exec -T app python -c "$HEALTH_PY" 2>/dev/null | tail -n 1 || true)"
    status="${out%% *}"
    version="${out#* }"
    if [[ "$status" == "ok" && "$version" == "$tag" ]] &&
      ! compose_tag "$tag" exec -T web wget -q -O /dev/null http://127.0.0.1:8081/api/ops/health >/dev/null 2>&1; then
      # The app is fine but Caddy (SPA + proxy) is not serving: not a successful update.
      status="web-unhealthy"
    elif [[ "$status" == "ok" && "$version" == "$tag" ]]; then
      if [[ -n "${UPDATE_HEALTH_URL:-}" ]]; then
        if curl -fsS -k --max-time 5 "$UPDATE_HEALTH_URL" >/dev/null 2>&1; then
          log "healthy: app $tag (and $UPDATE_HEALTH_URL) after $i check(s)"
          return 0
        fi
        status="proxy-unreachable"
      else
        log "healthy: app $tag after $i check(s)"
        return 0
      fi
    fi
    log "health $i/$HEALTH_RETRIES: status=${status:-none} version=${version:--} (want ok $tag)"
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

record() {
  # Append one JSON line for the ops status page (FEATURES 13.10).
  local result="$1" detail="$2" dir line
  dir="$(env_get BACKUP_HOST_DIR)"
  dir="${dir:-/srv/hospital/backups}/status"
  line="$(printf '{"version":1,"type":"update","status":"%s","from_tag":"%s","to_tag":"%s","started_at":"%s","finished_at":"%s","migrations_applied":%s,"db_restored":%s,"backup":"%s","detail":"%s","log":"%s"}' \
    "$result" "$PREV_TAG" "$NEW_TAG" "$STARTED_AT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$([[ $MIGRATED -eq 1 ]] && echo true || echo false)" \
    "$([[ $DB_RESTORED -eq 1 ]] && echo true || echo false)" \
    "$DUMP" "$(printf '%s' "$detail" | tr '"\\\n' "'/ ")" "$LOG_FILE")"
  if [[ -d "$dir" && -w "$dir" ]]; then
    printf '%s\n' "$line" >>"$dir/update-runs.jsonl" && return 0
  fi
  # status/ belongs to the backup container's postgres user: append through that container.
  if printf '%s\n' "$line" | compose run --rm --no-deps -T backup \
    bash -c 'cat >> /backups/status/update-runs.jsonl' >/dev/null 2>&1; then
    return 0
  fi
  warn "could not record the run in $dir/update-runs.jsonl"
}

# ------------------------------------------------------------------------------------ state
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PREV_TAG="$(env_get APP_IMAGE_TAG)"
REGISTRY="$(env_get IMAGE_REGISTRY)"
REGISTRY="${REGISTRY:-hospital-sys}"
PENDING=0
STOPPED=0
MIGRATED=0
SWAPPED=0
DB_RESTORED=0
DUMP=""
LOCK_FILE="$STATE_DIR/.update.flock"
STATE_FILE="$STATE_DIR/.update.state"
LOCKED=0

command -v docker >/dev/null 2>&1 || { log "docker not found"; exit 2; }
docker compose version >/dev/null 2>&1 || { log "docker compose v2 plugin not found"; exit 2; }
mkdir -p "$STATE_DIR"
# flock(2) on fd 8: released by the kernel when this process ends for any reason (crash, kill,
# power cut), so a dead update can never block the next one. perl does the same where flock(1)
# is missing (macOS).
exec 8>>"$LOCK_FILE"
if command -v flock >/dev/null 2>&1; then
  flock -n 8 || { log "another update is running (lock $LOCK_FILE held by $(head -n 1 "$LOCK_FILE" 2>/dev/null))"; exit 1; }
else
  perl -MFcntl=:flock -e 'open(my $fh, ">&=", 8) or exit 2; flock($fh, LOCK_EX | LOCK_NB) or exit 1' ||
    { log "another update is running (lock $LOCK_FILE held by $(head -n 1 "$LOCK_FILE" 2>/dev/null))"; exit 1; }
fi
LOCKED=1
printf 'pid=%s host=%s since=%s\n' "$$" "$(hostname)" "$STARTED_AT" >"$LOCK_FILE"

save_state() {
  # One small file, replaced atomically, describing what this run has done so far.
  local tmp="$STATE_FILE.tmp.$$"
  printf 'target=%s\nfrom=%s\nstep=%s\nmigrated=%s\nswapped=%s\ndump=%s\nstarted=%s\nlog=%s\n' \
    "$NEW_TAG" "$PREV_TAG" "$STEP" "$MIGRATED" "$SWAPPED" "$DUMP" "$STARTED_AT" "$LOG_FILE" >"$tmp"
  mv -f "$tmp" "$STATE_FILE"
}

state_get() { grep -E "^$1=" "$2" 2>/dev/null | head -n 1 | cut -d= -f2-; }

if [[ -f "$STATE_FILE" ]]; then
  # A previous run ended without its EXIT handler (power cut, SIGKILL). .env still names the
  # last committed tag (PREV_TAG), which is what a rollback returns to; containers may be on
  # the interrupted target. This run re-does every step, so it finishes the job (same tag) or
  # replaces it (another tag); either way it ends in a known state.
  warn "a previous update to $(state_get target "$STATE_FILE") was interrupted during '$(state_get step "$STATE_FILE")'"
  warn "  (migrations applied: $(state_get migrated "$STATE_FILE"), swapped: $(state_get swapped "$STATE_FILE"), pre-update dump: $(state_get dump "$STATE_FILE"), log: $(state_get log "$STATE_FILE"))"
  warn "  .env still says APP_IMAGE_TAG=${PREV_TAG:-<none>}; this run takes it from here"
fi

rollback() {
  local reason="$1" code=1 failed_step="$STEP"
  trap '' INT TERM # a half-finished rollback is worse than a slow one
  log "!!! update to $NEW_TAG failed during '$failed_step': $reason"
  if [[ $SWAPPED -eq 0 && $MIGRATED -eq 0 && $STOPPED -eq 0 ]]; then
    log "nothing was changed; still running ${PREV_TAG:-the current version}"
    record "failed" "$reason (during $failed_step; nothing changed)"
    return 1
  fi
  if [[ -z "$PREV_TAG" ]]; then
    log "no previous APP_IMAGE_TAG in $ENV_FILE: cannot roll back automatically"
    record "failed" "$reason (no previous tag)"
    return 3
  fi
  if [[ $MIGRATED -eq 1 ]]; then
    if [[ $RESTORE_DB -eq 1 && -n "$DUMP" ]]; then
      step "rollback: restore database from $DUMP"
      compose stop app || true
      if compose run --rm --no-deps -T backup /opt/backup/restore-dump.sh --dump "$DUMP" --yes; then
        DB_RESTORED=1
      else
        log "!!! database restore FAILED; the database still has the $NEW_TAG schema"
        code=3
      fi
    else
      warn "migrations of $NEW_TAG were applied; $PREV_TAG may not work with the new schema."
      warn "To also restore the pre-update database run:"
      warn "  infra/compose.sh stop app"
      warn "  infra/compose.sh run --rm --no-deps -T backup /opt/backup/restore-dump.sh --dump $DUMP --yes"
      warn "  infra/compose.sh up -d app web"
      warn "or re-run this update with --restore-db-on-failure."
    fi
  fi
  step "rollback: start $PREV_TAG"
  if compose_tag "$PREV_TAG" up -d --no-deps app web && check_health "$PREV_TAG"; then
    log "rolled back: $PREV_TAG is serving again"
  else
    log "!!! rollback to $PREV_TAG is NOT healthy: follow docs/runbooks/update-rollback.md now"
    code=3
  fi
  record "rolled_back" "$reason (during $failed_step)"
  return $code
}

finish() {
  local code=$?
  # Reached on success and after a completed rollback alike: the system is in a known state.
  [[ $LOCKED -eq 1 ]] && rm -f "$STATE_FILE"
  log "log file: $LOG_FILE"
  exit "$code"
}
fail() {
  local code=0
  rollback "$1" || code=$?
  exit "$code"
}
trap finish EXIT
trap 'fail "interrupted by signal"' INT TERM

log "update ${PREV_TAG:-<none>} -> $NEW_TAG (registry $REGISTRY)"
[[ "$PREV_TAG" == "$NEW_TAG" ]] && warn "$NEW_TAG is already the configured tag; redeploying it"

# ------------------------------------------------------------------------------------ 1. images
step "1/7 get images"
if [[ -n "$ARCHIVE" ]]; then
  docker load -i "$ARCHIVE" || fail "docker load failed"
else
  compose_tag "$NEW_TAG" pull app web || fail "pull failed (no internet? use --image-archive)"
fi
for img in "$REGISTRY/app:$NEW_TAG" "$REGISTRY/web:$NEW_TAG"; do
  docker image inspect "$img" >/dev/null 2>&1 || fail "image $img is not available locally"
done

# ------------------------------------------------------------------------------------ 2. preflight
step "2/7 preflight: system checks and migration plan (dry run)"
# The plan is read through the `migrate` service, as the owner role: its login is proven here,
# before anything is stopped or changed. (Step 4 re-applies both role passwords from .env.)
compose_tag "$NEW_TAG" run --rm --no-deps -T app manage check || fail "Django system checks failed on $NEW_TAG"
compose_tag "$NEW_TAG" run --rm --no-deps -T migrate manage migrate --plan || fail "migrate --plan failed"
if compose_tag "$NEW_TAG" run --rm --no-deps -T migrate manage migrate --check >/dev/null 2>&1; then
  log "no pending migrations"
else
  PENDING=1
  log "migrations are pending (see plan above)"
fi

if [[ $DRY_RUN -eq 1 ]]; then
  log "dry run: stopping before backup, migrations and swap"
  exit 0
fi

if [[ $ASSUME_YES -ne 1 ]]; then
  if [[ -t 0 ]]; then
    printf 'Proceed with backup, %s and swap to %s? [y/N] ' "$([[ $PENDING -eq 1 ]] && echo migrations || echo 'no migrations')" "$NEW_TAG"
    read -r answer
    [[ "$answer" == "y" || "$answer" == "Y" ]] || { log "aborted by operator"; exit 1; }
  else
    log "non-interactive: pass --yes to proceed"
    exit 1
  fi
fi

# ------------------------------------------------------------------------------------ 3. backup
if [[ $PENDING -eq 1 ]]; then
  step "3/7 maintenance: stop app so the backup is the last write before migrating"
  STOPPED=1
  compose stop app || fail "could not stop app"
fi
step "3/7 pre-update backup"
set +e
DUMP="$(compose run --rm --no-deps -T backup /opt/backup/backup-nightly.sh --label "pre-update-$NEW_TAG" --no-pgbackrest --no-prune | tail -n 1)"
backup_rc=$?
set -e
# Exit 3 = partial: the database dump is verified and printed, only the media archive failed.
# The dump is what a rollback restores, so the update may go on (with a loud warning).
case "$backup_rc" in
  0) ;;
  3) warn "pre-update backup is PARTIAL (database dump ok; see the backup log for what failed)" ;;
  *) fail "pre-update backup failed (exit $backup_rc); nothing was changed" ;;
esac
[[ "$DUMP" == /backups/dumps/*.dump ]] || fail "backup did not report a dump path (got '$DUMP')"
log "pre-update dump: $DUMP"
save_state

# ------------------------------------------------------------------------------------ 4. migrate
# Ownership and grants first: a migration run as the owner must own every object it alters,
# and the tables it creates reach the app role through the owner's default privileges.
step "4/7 database roles"
"$ROOT/infra/db-roles.sh" --no-generate || fail "database roles could not be applied or verified"
if [[ $PENDING -eq 1 ]]; then
  step "4/7 apply migrations with $NEW_TAG"
  MIGRATED=1 # set first: a partly applied run still changed the schema
  save_state
  compose_tag "$NEW_TAG" run --rm --no-deps -T migrate migrate || fail "migrations failed"
else
  step "4/7 no migrations to apply"
fi

# ------------------------------------------------------------------------------------ 5. swap
step "5/7 swap app and web to $NEW_TAG"
SWAPPED=1
save_state
compose_tag "$NEW_TAG" up -d --no-deps app web || fail "could not start $NEW_TAG"

# ------------------------------------------------------------------------------------ 6. health
step "6/7 health check"
check_health "$NEW_TAG" || fail "$NEW_TAG did not become healthy"

# ------------------------------------------------------------------------------------ 7. commit
step "7/7 commit"
env_set APP_IMAGE_TAG "$NEW_TAG"
record "ok" "updated"
log "updated ${PREV_TAG:-<none>} -> $NEW_TAG. Old images can be removed later with: docker image prune"
