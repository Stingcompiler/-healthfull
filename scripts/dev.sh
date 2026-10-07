#!/usr/bin/env bash
# Run the Django backend and the Vite frontend together (make dev).
# Ctrl-C (or either process exiting) stops both, including their child processes.
#
# Ports come from BACKEND_PORT / FRONTEND_PORT, else scripts/ports.sh derives them per worktree.
# Vite proxies /api and /admin to http://127.0.0.1:$BACKEND_PORT (frontend/vite.config.ts).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/ports.sh
source "$ROOT/scripts/ports.sh"

if [[ ! -f "$ROOT/backend/manage.py" ]]; then
  echo "dev: backend/manage.py not found; run from a complete checkout" >&2
  exit 1
fi
if [[ ! -f "$ROOT/frontend/package.json" ]]; then
  echo "dev: frontend/package.json not found; run from a complete checkout" >&2
  exit 1
fi

# Job control puts each background job in its own process group, so we can stop
# the whole tree (uv -> python -> autoreloader child, pnpm -> node) with one signal.
set -m

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local status=$?
  trap - INT TERM EXIT
  echo
  echo "dev: stopping backend and frontend..."
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    [[ -n "$pid" ]] && kill -TERM -- "-$pid" 2>/dev/null || true
  done
  # Give them a moment, then force.
  for _ in 1 2 3 4 5; do
    alive=0
    for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
      [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && alive=1
    done
    [[ $alive -eq 0 ]] && break
    sleep 1
  done
  for pid in "$BACKEND_PID" "$FRONTEND_PID"; do
    [[ -n "$pid" ]] && kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit "$status"
}
trap cleanup INT TERM EXIT

echo "dev: backend  http://127.0.0.1:${BACKEND_PORT}  (DB_NAME=${DB_NAME:-hospital_dev})"
echo "dev: frontend http://127.0.0.1:${FRONTEND_PORT}"

# stdin from /dev/null: a background job that reads the terminal would be stopped (SIGTTIN).
(cd "$ROOT/backend" && exec uv run python manage.py runserver "127.0.0.1:${BACKEND_PORT}") </dev/null &
BACKEND_PID=$!
(cd "$ROOT/frontend" && exec pnpm dev) </dev/null &
FRONTEND_PID=$!

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "dev: backend exited; stopping frontend" >&2
else
  echo "dev: frontend exited; stopping backend" >&2
fi
exit 1
