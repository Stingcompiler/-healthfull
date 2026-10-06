#!/usr/bin/env bash
# Tiny assertion helpers for the infra shell tests. Sourced.

PASSED=0

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  PASSED=$((PASSED + 1))
  echo "ok - $*"
}

summary() {
  echo "all $PASSED checks passed: $(basename "$0")"
}

assert_eq() {
  [[ "$1" == "$2" ]] || fail "${3:-values differ}: expected '$2', got '$1'"
}

assert_match() {
  [[ "$1" =~ $2 ]] || fail "${3:-no match}: '$1' does not match /$2/"
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file: $1"
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'; else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# JSON checks use python3 so the tests verify the files really are valid JSON lines.
_json_get() {
  # _json_get FILE LINE_INDEX DOTTED.PATH -> value (lists by index; dicts by key)
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
path, index, dotted = sys.argv[1], int(sys.argv[2]), sys.argv[3]
with open(path, encoding="utf-8") as fh:
    lines = [json.loads(line) for line in fh if line.strip()]  # every line must parse
value = lines[index]
for part in dotted.split("."):
    value = value[int(part)] if isinstance(value, list) else value[part]
if isinstance(value, (list, dict)):
    print(len(value))
elif value is None:
    print("null")
else:
    print(value)
PY
}

assert_json_field() {
  local got
  got="$(_json_get "$1" "$2" "$3")" || fail "cannot read $3 from $1"
  assert_eq "$got" "$4" "json $3"
}

assert_json_count() {
  assert_json_field "$@"
}

assert_json_contains() {
  local got
  got="$(_json_get "$1" "$2" "$3")" || fail "cannot read $3 from $1"
  [[ "$got" == *"$4"* ]] || fail "json $3: '$got' does not contain '$4'"
}
