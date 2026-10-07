#!/usr/bin/env bash
# Print the worktree id used to isolate parallel checkouts (docs/ARCHITECTURE.md section 3):
#   first 8 hex chars of sha1(<physical absolute path of the repo root>), no trailing newline hashed.
# The backend settings and the e2e config compute the same value; keep them in sync.
#
# Usage: scripts/repo-hash.sh           -> e.g. 1a2b3c4d
#        scripts/repo-hash.sh --root    -> the repo root path that is hashed
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ "${1:-}" == "--root" ]]; then
  printf '%s\n' "$root"
  exit 0
fi

if command -v sha1sum >/dev/null 2>&1; then
  sum="$(printf '%s' "$root" | sha1sum)"
elif command -v shasum >/dev/null 2>&1; then
  sum="$(printf '%s' "$root" | shasum -a 1)"
elif command -v openssl >/dev/null 2>&1; then
  sum="$(printf '%s' "$root" | openssl dgst -sha1 -r)"
else
  echo "repo-hash: need sha1sum, shasum or openssl" >&2
  exit 1
fi

printf '%s\n' "${sum:0:8}"
