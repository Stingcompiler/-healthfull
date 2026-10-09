#!/usr/bin/env bash
# Entrypoint of the app image.
#   serve            wait for the database, optionally migrate, run gunicorn (default)
#   migrate [args]   wait for the database, run `manage.py migrate --noinput [args]`
#   auto-migrate     `migrate` when MIGRATE_ON_START is true, else only wait for the database
#                    (the compose `migrate` service, which connects as the owner role; the
#                    app itself connects as a role that cannot change the schema)
#   manage ARGS      run any management command (e.g. manage createsuperuser)
#   maintenance-loop run the maintenance cycle now and then every MAINTENANCE_INTERVAL_SECONDS
#                    [3600] (the compose `maintenance` service). Each cycle, all idempotent:
#                      manage.py maintenance        expired sessions, stale login throttles
#                      manage.py notify_scan        time-based alerts (FEATURES 0.13), once a day
#                      manage.py charge_bed_nights  passed bed nights of open admissions (10.5),
#                                                   as BED_CHARGE_USER; skipped when it is unset
#   maintenance-once one maintenance cycle, then exit
#   anything else    exec as-is (e.g. bash)
set -euo pipefail

wait_for_db() {
  python - <<'PY'
import os, sys, time

import psycopg

timeout = float(os.environ.get("DB_WAIT_SECONDS", "90"))
deadline = time.monotonic() + timeout
dbname = os.environ.get("DB_NAME", "hospital")
while True:
    try:
        # Host, port, user and password come from the standard PG* environment variables.
        psycopg.connect(dbname=dbname, connect_timeout=3).close()
        break
    except psycopg.OperationalError as exc:
        if time.monotonic() > deadline:
            print(f"app-entrypoint: database not reachable after {timeout:.0f}s: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY
}

is_true() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1 | true | yes | on) return 0 ;;
    *) return 1 ;;
  esac
}

maintenance_cycle() {
  # Each job is idempotent and independent: one failing never skips the others.
  python manage.py maintenance || echo "app-entrypoint: maintenance failed; retrying next cycle" >&2
  python manage.py notify_scan || echo "app-entrypoint: notify_scan failed; retrying next cycle" >&2
  if [[ -n "${BED_CHARGE_USER:-}" ]]; then
    python manage.py charge_bed_nights --as "$BED_CHARGE_USER" ||
      echo "app-entrypoint: charge_bed_nights failed; retrying next cycle" >&2
  else
    echo "app-entrypoint: BED_CHARGE_USER is not set; bed nights are charged from the bed board and at discharge only"
  fi
}

cmd="${1:-serve}"
case "$cmd" in
  serve)
    wait_for_db
    if is_true "${MIGRATE_ON_START:-false}"; then
      echo "app-entrypoint: MIGRATE_ON_START is set; applying migrations"
      python manage.py migrate --noinput
    fi
    # Workers, threads, timeouts and logging come from backend/gunicorn.conf.py
    # (WEB_CONCURRENCY, GUNICORN_THREADS, GUNICORN_TIMEOUT). Only container specifics here:
    # the app is reachable solely from Caddy on the private Docker network, so forwarded
    # headers from any peer on that network are trusted.
    if [[ -f /app/gunicorn.conf.py ]]; then set -- --config /app/gunicorn.conf.py; else set --; fi
    exec gunicorn config.wsgi:application "$@" \
      --bind 0.0.0.0:8000 \
      --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
      --worker-tmp-dir /dev/shm \
      --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
      --max-requests-jitter 100
    ;;
  migrate)
    shift
    wait_for_db
    exec python manage.py migrate --noinput "$@"
    ;;
  auto-migrate)
    wait_for_db
    if is_true "${MIGRATE_ON_START:-false}"; then
      echo "app-entrypoint: MIGRATE_ON_START is set; applying migrations as ${PGUSER:-<default>}"
      exec python manage.py migrate --noinput
    fi
    echo "app-entrypoint: MIGRATE_ON_START is off; schema left as it is (infra/update.sh migrates)"
    ;;
  manage)
    shift
    exec python manage.py "$@"
    ;;
  maintenance-once)
    wait_for_db
    maintenance_cycle
    ;;
  maintenance-loop)
    wait_for_db
    interval="${MAINTENANCE_INTERVAL_SECONDS:-3600}"
    case "$interval" in '' | *[!0-9]* | 0) echo "app-entrypoint: bad MAINTENANCE_INTERVAL_SECONDS" >&2; exit 2 ;; esac
    while true; do
      maintenance_cycle
      # Background sleep + wait: a stop signal ends the loop at once.
      sleep "$interval" &
      wait $!
    done
    ;;
  *)
    exec "$@"
    ;;
esac
