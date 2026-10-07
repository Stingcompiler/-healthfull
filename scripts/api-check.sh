#!/usr/bin/env bash
# Fail when the generated API contract drifts from what is checked in (make api-check).
# Run AFTER regeneration (make api). Compares the working tree with the git index, so
# regenerated-and-staged files pass while forgotten regenerations fail.
#
# Untracked files: a hard failure in CI (CI=true), a warning locally so a fresh
# branch can run `make check` before its first commit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

FILES="frontend/openapi.json frontend/src/lib/api/schema.d.ts"
status=0

for f in $FILES; do
  if [[ ! -f "$f" ]]; then
    echo "api-check: $f was not generated" >&2
    status=1
    continue
  fi
  if ! git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
    if [[ "${CI:-}" == "true" ]]; then
      echo "api-check: $f is not committed" >&2
      status=1
    else
      echo "api-check: warning: $f is untracked; commit it with the change that produced it" >&2
    fi
  fi
done

# shellcheck disable=SC2086 # FILES is a fixed, space-free list
if ! git diff --exit-code --stat -- $FILES; then
  echo >&2
  echo "api-check: the API contract drifted. Run 'make api' and commit frontend/openapi.json" >&2
  echo "           and frontend/src/lib/api/schema.d.ts together with the backend change." >&2
  # shellcheck disable=SC2086
  git --no-pager diff -- $FILES | head -n 80 >&2 || true
  status=1
fi

if [[ $status -eq 0 ]]; then
  echo "api-check: frontend/openapi.json and schema.d.ts match the backend"
fi
exit $status
