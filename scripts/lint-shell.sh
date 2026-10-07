#!/usr/bin/env bash
# Syntax-check every shell script we own with `bash -n`, and run shellcheck when it is installed
# (CI runners have it; it is optional locally). Exit non-zero on any finding.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

files=()
while IFS= read -r f; do
  files+=("$f")
done < <(find scripts infra agent -type f \( -name '*.sh' -o -path '*/fake-docker/*' \) \
  -not -path '*/node_modules/*' -not -path '*/.venv/*' 2>/dev/null | sort)

if [[ ${#files[@]} -eq 0 ]]; then
  echo "lint-shell: no shell scripts found"
  exit 0
fi

status=0
for f in "${files[@]}"; do
  if ! bash -n "$f"; then
    echo "lint-shell: syntax error in $f" >&2
    status=1
  fi
done
echo "lint-shell: bash -n checked ${#files[@]} scripts"

if command -v shellcheck >/dev/null 2>&1; then
  # Warning level and above; info/style notes are advisory.
  if shellcheck -x --severity=warning "${files[@]}"; then
    echo "lint-shell: shellcheck clean"
  else
    status=1
  fi
else
  echo "lint-shell: shellcheck not installed; skipped (CI runs it)"
fi

exit $status
