#!/usr/bin/env bash
# .env helpers shared by infra/update.sh and infra/db-roles.sh. Sourced, never executed.
# Both functions work on ENV_FILE (absolute path, set by the caller).

env_get() {
  # Last KEY=VALUE in the env file; surrounding quotes stripped. Never `source` the file.
  local line
  line="$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

env_set() {
  # Replace (or append) KEY=VALUE atomically: the new content goes to a temp file in the same
  # directory (cp -p first, so it already has the file's owner and mode), is flushed to disk,
  # then renamed over .env. A power cut leaves either the old or the new file, never a torn
  # one (which would lose POSTGRES_PASSWORD, DJANGO_SECRET_KEY and the backup passphrases).
  local key="$1" value="$2" tmp
  tmp="$(mktemp "$(dirname "$ENV_FILE")/.env.update.XXXXXX")"
  cp -p "$ENV_FILE" "$tmp"
  if grep -qE "^[[:space:]]*$key=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" '
      $0 ~ "^[[:space:]]*" k "=" { if (!done) { print k "=" v; done = 1 }; next }
      { print }' "$ENV_FILE" >"$tmp"
  else
    # The file may not end with a newline: never glue the new line onto the last one.
    [[ -s "$tmp" && "$(tail -c 1 "$tmp")" != "" ]] && printf '\n' >>"$tmp"
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
  fi
  sync "$tmp" 2>/dev/null || sync
  mv -f "$tmp" "$ENV_FILE"
  sync "$(dirname "$ENV_FILE")" 2>/dev/null || sync
}
