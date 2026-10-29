#!/usr/bin/env bash
# X-Forwarded-For through the compose Caddy (infra/Caddyfile, ADR 0028 decision 6).
#   - CADDY_TRUSTED_PROXIES empty (default, the LAN edge): a forged header is overwritten with
#     the connection address, so a client cannot choose the address the app sees.
#   - set to the peer's range (behind a host reverse proxy): the header that proxy set survives,
#     with the peer appended, so the app sees the real visitor.
#   - set to a range that does not contain the peer: overwritten again.
# Both configurations must pass `caddy validate`.
#
# Runs the real Caddyfile with the caddy binary at CADDY_BIN (default: caddy on PATH; CI uses
# the one copied out of the web image) in front of a tiny Python upstream that echoes the
# header it received. Skips without a caddy binary unless REQUIRE_CADDY=1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CADDYFILE="$(cd "$HERE/.." && pwd -P)/Caddyfile"
# shellcheck source=infra/tests/testlib.sh
source "$HERE/testlib.sh"

CADDY_BIN="${CADDY_BIN:-$(command -v caddy || true)}"
if [[ -z "$CADDY_BIN" || ! -x "$CADDY_BIN" ]]; then
  if [[ "${REQUIRE_CADDY:-0}" == "1" ]]; then
    echo "FAIL: no caddy binary and REQUIRE_CADDY=1 (set CADDY_BIN)" >&2
    exit 1
  fi
  echo "SKIP: no caddy binary (install caddy or set CADDY_BIN)"
  summary
  exit 0
fi
"$CADDY_BIN" version

WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-caddy-xff-test.XXXXXX")"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT
export XDG_DATA_HOME="$WORK/data" XDG_CONFIG_HOME="$WORK/config"

free_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

UPSTREAM_PORT="$(free_port)"
cat >"$WORK/echo.py" <<'PY'
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Echo(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = (self.headers.get("X-Forwarded-For") or "<none>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Echo).serve_forever()
PY
python3 "$WORK/echo.py" "$UPSTREAM_PORT" &
PIDS+=("$!")

# Environment of one compose web container, with this test's ports.
caddy_env() {
  env CADDY_SITE_ADDRESS="http://127.0.0.1:$SITE_PORT" APP_UPSTREAM="127.0.0.1:$UPSTREAM_PORT" \
    CADDY_TRUSTED_PROXIES="$1" "${@:2}"
}

# Through Caddy with a forged X-Forwarded-For, under CADDY_TRUSTED_PROXIES=$1; prints what the
# upstream received.
forwarded_for() {
  SITE_PORT="$(free_port)"
  caddy_env "$1" "$CADDY_BIN" run --adapter caddyfile --config "$CADDYFILE" >"$WORK/caddy.log" 2>&1 &
  local pid=$!
  local out=""
  for _ in $(seq 1 50); do
    if out="$(curl -fsS -H "X-Forwarded-For: 203.0.113.7" "http://127.0.0.1:$SITE_PORT/api/echo" 2>/dev/null)"; then
      break
    fi
    out=""
    sleep 0.2
  done
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  [[ -n "$out" ]] || { cat "$WORK/caddy.log" >&2; fail "caddy (CADDY_TRUSTED_PROXIES='$1') never answered"; }
  printf '%s' "$out"
}

SITE_PORT=80
for value in "" "127.0.0.1/32" "private_ranges" "10.0.0.0/8 127.0.0.0/8"; do
  caddy_env "$value" "$CADDY_BIN" validate --adapter caddyfile --config "$CADDYFILE" >"$WORK/validate.log" 2>&1 \
    || { cat "$WORK/validate.log" >&2; fail "caddy validate with CADDY_TRUSTED_PROXIES='$value'"; }
done
pass "caddy validate accepts CADDY_TRUSTED_PROXIES empty, one CIDR, private_ranges and a list"

if caddy_env "not-an-address" "$CADDY_BIN" validate --adapter caddyfile --config "$CADDYFILE" >/dev/null 2>&1; then
  fail "a malformed CADDY_TRUSTED_PROXIES must fail validation"
fi
pass "a malformed CADDY_TRUSTED_PROXIES fails validation (the container would not start)"

assert_eq "$(forwarded_for "")" "127.0.0.1" "unset: the forged header is replaced"
pass "unset: a forged X-Forwarded-For is overwritten with the connection address"

assert_eq "$(forwarded_for "10.0.0.0/8")" "127.0.0.1" "untrusted peer: replaced"
pass "a peer outside CADDY_TRUSTED_PROXIES cannot pass a header through"

assert_eq "$(forwarded_for "127.0.0.1/32")" "203.0.113.7, 127.0.0.1" "trusted peer: kept, peer appended"
pass "a trusted peer's X-Forwarded-For is kept and the peer appended"

assert_eq "$(forwarded_for "private_ranges")" "203.0.113.7, 127.0.0.1" "private_ranges covers loopback"
pass "private_ranges trusts a peer on a private or loopback address"

summary
