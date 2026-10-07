#!/usr/bin/env bash
# docker compose for the hospital-sys stack with the repo-root .env, from any directory.
#   infra/compose.sh up -d
#   infra/compose.sh logs -f app
#   infra/compose.sh run --rm app manage createsuperuser
# ENV_FILE overrides the env file path (default: <repo>/.env).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "compose: $ENV_FILE not found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi
# Absolute, and exported: docker-compose.yml reads it for every service's env_file too, so the
# containers get the same file that compose interpolated from.
ENV_FILE="$(cd "$(dirname "$ENV_FILE")" && pwd -P)/$(basename "$ENV_FILE")"
export ENV_FILE

exec docker compose --env-file "$ENV_FILE" -f "$ROOT/infra/docker-compose.yml" "$@"
