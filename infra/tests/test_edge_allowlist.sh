#!/usr/bin/env bash
# The public edge for a LAN install (infra/edge/edge.caddy, ADR 0028 decisions 3, 5 and 6).
#   - Every operation of the API contract (frontend/openapi.json) is sent through the edge: it is
#     forwarded if and only if it is a /api/portal operation that is public or authenticates a
#     patient (PortalAuth) or a guest (GuestAuth), or GET /api/auth/csrf, or GET /api/ops/site.
#     A new staff operation can never slip through, and a new public one fails here until it is
#     listed in the edge on purpose.
#   - The staff surface is refused by name: /api/auth/*, /api/visits/*, /administration*,
#     /sign-in, /login, /admin, /static, staff screens, the staff-session portal operations,
#     wrong methods, dot segments, escapes and doubled slashes.
#   - The SPA bundle and the public client routes are forwarded; refused pages get the fallback
#     page (404), a down tunnel or center gets it with 503; refused API calls get JSON.
#   - A forged X-Forwarded-For is overwritten with the connection address; Host is kept.
#   - The example host Caddyfile validates, and the center-side compose Caddyfile accepts the
#     tunnel settings of docs/runbooks/public-edge.md.
#
# Runs the real edge.caddy with the caddy binary at CADDY_BIN (default: caddy on PATH; CI uses the
# one copied out of the web image) in front of a tiny Python upstream that echoes what it got.
# Skips without a caddy binary unless REQUIRE_CADDY=1.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$HERE/../.." && pwd -P)"
EDGE_DIR="$ROOT/infra/edge"
OPENAPI="$ROOT/frontend/openapi.json"
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
assert_file "$EDGE_DIR/edge.caddy"
assert_file "$EDGE_DIR/fallback/index.html"
assert_file "$OPENAPI"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/infra-edge-test.XXXXXX")"
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

# --- upstream: answers every method with what it received, marked as the upstream ------------
UPSTREAM_PORT="$(free_port)"
cat >"$WORK/echo.py" <<'PY'
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Echo(BaseHTTPRequestHandler):
    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        # The center's own Caddy answers 502 when its app is down.
        status = 502 if self.path.startswith("/portal/center-down") else 200
        body = json.dumps(
            {
                "method": self.command,
                "path": self.path,
                "xff": self.headers.get("X-Forwarded-For"),
                "proto": self.headers.get("X-Forwarded-Proto"),
                "host": self.headers.get("Host"),
            }
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Edge-Test-Upstream", "1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _answer

    def log_message(self, *args: object) -> None:
        pass


HTTPServer(("127.0.0.1", int(sys.argv[1])), Echo).serve_forever()
PY
python3 "$WORK/echo.py" "$UPSTREAM_PORT" &
PIDS+=("$!")

CENTER_NAME="مركز الأمل الطبي"
CENTER_PHONE="+249 900 000 001"

# edge_config FILE PORT UPSTREAM: a host Caddyfile with one center site importing edge.caddy,
# like infra/edge/Caddyfile.example but on plain HTTP and any Host.
edge_config() {
  cat >"$1" <<EOF
{
	admin off
	auto_https off
}
http://:$2 {
	bind 127.0.0.1
	import $EDGE_DIR/edge.caddy $3 $EDGE_DIR/fallback "$CENTER_NAME" "$CENTER_PHONE"
}
EOF
}

# start_edge PORT UPSTREAM: runs an edge and waits until it answers.
start_edge() {
  local conf="$WORK/edge-$1.caddyfile"
  edge_config "$conf" "$1" "$2"
  "$CADDY_BIN" validate --adapter caddyfile --config "$conf" >"$WORK/validate.log" 2>&1 \
    || { cat "$WORK/validate.log" >&2; fail "caddy validate of the edge config"; }
  "$CADDY_BIN" run --adapter caddyfile --config "$conf" >"$WORK/edge-$1.log" 2>&1 &
  PIDS+=("$!")
  for _ in $(seq 1 50); do
    if curl -s -o /dev/null "http://127.0.0.1:$1/__edge_probe" 2>/dev/null; then return 0; fi
    sleep 0.2
  done
  cat "$WORK/edge-$1.log" >&2
  fail "the edge on port $1 never answered"
}

EDGE_PORT="$(free_port)"
start_edge "$EDGE_PORT" "127.0.0.1:$UPSTREAM_PORT"
pass "edge.caddy imported with its four arguments passes caddy validate and starts"

# request METHOD PATH [curl args...]: prints "<status> <forwarded:0|1>", body in $WORK/body,
# headers in $WORK/headers. The raw path is sent as is (no dot-segment cleaning by curl).
request() {
  local method="$1" path="$2"
  shift 2
  local status verb=(-X "$method")
  # curl -X HEAD would wait for a body that never comes.
  [[ "$method" == "HEAD" ]] && verb=(-I)
  status="$(curl -s --max-time 20 --path-as-is "${verb[@]}" -o "$WORK/body" -D "$WORK/headers" -w '%{http_code}' \
    -H 'Content-Type: application/json' "$@" "http://127.0.0.1:$EDGE_PORT$path")" || status="000"
  local forwarded=0
  if grep -qi '^X-Edge-Test-Upstream: 1' "$WORK/headers"; then forwarded=1; fi
  echo "$status $forwarded"
}

# --- 1. every operation of the API contract ---------------------------------------------------
# Lines "METHOD PATH EXPECTED OPERATION_ID", path parameters filled with 7.
python3 - "$OPENAPI" >"$WORK/operations.txt" <<'PY'
import json
import re
import sys

EDGE_EXTRA = {"auth_get_csrf", "ops_get_site"}
PUBLIC_KINDS = {None, "PortalAuth", "GuestAuth"}
schema = json.load(open(sys.argv[1], encoding="utf-8"))
for path, operations in sorted(schema["paths"].items()):
    for method, op in sorted(operations.items()):
        security = op.get("security")
        kinds = {next(iter(item)) for item in security} if security else {None}
        portal_public = path.startswith("/api/portal/") and kinds <= PUBLIC_KINDS
        expected = 1 if portal_public or op["operationId"] in EDGE_EXTRA else 0
        concrete = re.sub(r"\{[^}]+\}", "7", path)
        print(method.upper(), concrete, expected, op["operationId"])
PY
total=0
forwarded_count=0
while read -r method path expected op_id; do
  total=$((total + 1))
  read -r status forwarded < <(request "$method" "$path" --data '{}')
  if [[ "$op_id" == "auth_get_me" ]]; then
    assert_eq "$forwarded $status" "0 401" "GET /api/auth/me answers 401 at the edge"
    continue
  fi
  if [[ "$forwarded" != "$expected" ]]; then
    if [[ "$expected" == "1" ]]; then
      fail "$method $path ($op_id) is a public/patient/guest operation the edge does not forward: add it to infra/edge/edge.caddy on purpose"
    fi
    fail "$method $path ($op_id) is a staff operation the edge forwards (status $status)"
  fi
  if [[ "$forwarded" == "1" ]]; then
    forwarded_count=$((forwarded_count + 1))
  else
    assert_eq "$status" "404" "refused $method $path"
    assert_match "$(cat "$WORK/body")" '"code":"NOT_FOUND"' "refused $method $path answers JSON"
  fi
done <"$WORK/operations.txt"
[[ $total -gt 100 ]] || fail "only $total operations read from $OPENAPI"
[[ $forwarded_count -gt 30 ]] || fail "only $forwarded_count operations forwarded"
pass "all $total operations of the contract: exactly $forwarded_count public, patient and guest operations forwarded, every staff operation refused"

# --- 2. the staff surface by name --------------------------------------------------------------
refuse_api() { # METHOD PATH
  local out
  out="$(request "$1" "$2" --data '{}')"
  assert_eq "$out" "404 0" "$1 $2 must be refused"
  assert_match "$(cat "$WORK/body")" '"code":"NOT_FOUND"' "$1 $2 answers JSON"
}
refuse_page() { # PATH
  local out
  out="$(request GET "$1")"
  assert_eq "$out" "404 0" "GET $1 must be refused"
  grep -q "$CENTER_NAME" "$WORK/body" || fail "GET $1: the fallback page must carry the center name"
}

for p in /api/auth/login /api/auth/logout /api/auth/change-password /api/auth/me/preferences \
  /api/auth/csrf /api/auth/unknown; do
  refuse_api POST "$p"
done
for p in /api/auth/login /api/auth/me/preferences /api/auth /api/auth/; do
  refuse_api GET "$p"
done
assert_eq "$(request GET /api/auth/me -H 'Cookie: sessionid=abc')" "401 0" "/api/auth/me never reaches the center"
assert_match "$(cat "$WORK/body")" '"code":"NOT_AUTHENTICATED"' "/api/auth/me answers the app's 401 shape"
pass "/api/auth/*: only GET /api/auth/csrf is forwarded; /api/auth/me answers 401 at the edge"

for p in /api/visits /api/visits/ /api/visits/online-bookings /api/visits/online-bookings/7/approve \
  /api/visits/appointments /api/visits/queue; do
  refuse_api GET "$p"
  refuse_api POST "$p"
done
for p in /api/core/center/logo /api/core/public-site /api/billing/invoices /api/patients/7 \
  /api/ops/health /api/ops/status /api/ops/export /api/docs /api/openapi.json /api \
  /api/portal/access-codes /api/portal/patients/7/access-codes /api/portal/access-codes/7/revoke \
  /api/portal/ping /api/portal /api/portal/ /api/portal/session/ /api/portal/doctors/abc/days \
  /api/portal/center-media/7/extra; do
  refuse_api GET "$p"
  refuse_api POST "$p"
done
pass "staff routers, health and status, the API docs and the staff-session portal operations are refused"

for p in /sign-in /login /change-password /administration /administration/ /administration/public-site \
  /administrationx /admin /admin/ /admin/login/ /static/admin/css/base.css /queue /patients \
  /visits/online-bookings /cashier /display/queue /design /dashboard /portalx /verify; do
  refuse_page "$p"
done
pass "/sign-in, /login, /administration*, /admin, /static and every staff screen get the fallback page"

# Wrong methods on allowed paths.
refuse_api GET /api/portal/guest-bookings
refuse_api GET /api/portal/session/logout
refuse_api POST /api/portal/doctors
refuse_api POST /api/portal/center-page
refuse_api POST /api/ops/site
refuse_api DELETE /api/portal/session
refuse_api PUT /api/portal/appointments
refuse_api PATCH /api/portal/guest/booking
assert_eq "$(request POST /portal)" "404 0" "POST to a page is refused"
pass "an allowed path with another method is refused"

# Dot segments, escapes, doubled and back slashes never reach the center.
for p in /portal/../api/auth/login /portal/../administration /verify/../api/visits/queue \
  /api/portal/doctors/7/../../access-codes /api/portal/./session /portal/%2e%2e/api/auth/login \
  /api/portal/%73ession /api/portal/session%2f..%2faccess-codes //api/portal/session \
  /api/portal//session '/portal/..\api/auth/login' /assets/../api/auth/login; do
  out="$(request GET "$p")"
  [[ "${out#* }" == "0" ]] || fail "GET $p was forwarded"
  out="$(request POST "$p" --data '{}')"
  [[ "${out#* }" == "0" ]] || fail "POST $p was forwarded"
done
pass "dot segments, escapes, doubled and back slashes are refused before routing"

# --- 3. what is forwarded ----------------------------------------------------------------------
for p in / /portal /portal/ /portal/book /portal/booking /portal/sign-in /portal/visits/7 \
  /verify/abc_DEF-123 /index.html /boot.js /favicon.svg /robots.txt /portal.webmanifest \
  /portal-icon-192.png /portal-icon-512.png /portal-icon-maskable-512.png /assets/index-abc.js \
  /assets/ibm-plex-sans-arabic.woff2 '/api/portal/verify?receipt=R-1&token=abc' \
  '/api/portal/doctors/12/slots?day=2026-11-01'; do
  assert_eq "$(request GET "$p")" "200 1" "GET $p must be forwarded"
done
assert_eq "$(request HEAD /portal)" "200 1" "HEAD of a public page"
pass "the SPA files, /, /portal*, /verify/* and parameterized public reads are forwarded"

# The forwarded request keeps the path and query as sent, and the visitor's Host.
request GET '/api/portal/doctors/12/days?from=2026-11-01' -H 'Host: center.example.sd' >/dev/null
assert_match "$(cat "$WORK/body")" '"path": "/api/portal/doctors/12/days\?from=2026-11-01"' "path and query kept"
assert_match "$(cat "$WORK/body")" '"host": "center.example.sd"' "Host kept"
pass "path, query and the public Host reach the center unchanged"

# --- 4. X-Forwarded-For: overwritten with the connection address (ADR 0028 decision 6) ---------
request GET /api/ops/site -H 'X-Forwarded-For: 203.0.113.7' -H 'X-Forwarded-Proto: https' >/dev/null
assert_match "$(cat "$WORK/body")" '"xff": "127.0.0.1"' "a forged X-Forwarded-For is replaced"
assert_match "$(cat "$WORK/body")" '"proto": "http"' "a forged X-Forwarded-Proto is replaced"
pass "a forged X-Forwarded-For and X-Forwarded-Proto are overwritten with what the edge saw"

# --- 5. the body limit -------------------------------------------------------------------------
head -c 300000 /dev/zero | tr '\0' 'a' >"$WORK/big"
out="$(request POST /api/portal/guest-bookings --data-binary "@$WORK/big")"
[[ "${out%% *}" == "413" ]] || fail "a 300 KB body must be refused with 413, got $out"
pass "a request body over 256 KB is refused"

# --- 6. the fallback page ----------------------------------------------------------------------
request GET /sign-in >/dev/null
body="$(cat "$WORK/body")"
assert_match "$body" "$CENTER_NAME" "fallback: center name"
assert_match "$body" "tel:\\+249 900 000 001" "fallback: phone link"
assert_match "$body" 'dir="rtl"' "fallback: Arabic first"
[[ "$body" != *"<script"* && "$body" != *"http://"* && "$body" != *"https://"* ]] \
  || fail "the fallback page must load nothing from anywhere"
[[ "$body" != *"{{"* ]] || fail "the fallback page template was not rendered"
assert_match "$(cat "$WORK/headers")" "Content-Security-Policy: default-src 'none'" "fallback: CSP"
pass "the fallback page names the center and its phone, Arabic first, self-contained, under a strict CSP"

assert_eq "$(request GET /portal/center-down)" "503 0" "the center's 502 becomes the fallback"
grep -q "$CENTER_NAME" "$WORK/body" || fail "center down: the fallback page"
pass "a page whose center answers 502 gets the fallback page with 503"

DOWN_PORT="$(free_port)"
DEAD_UPSTREAM="127.0.0.1:$(free_port)"
EDGE_UP="$EDGE_PORT"
start_edge "$DOWN_PORT" "$DEAD_UPSTREAM"
EDGE_PORT="$DOWN_PORT"
assert_eq "$(request GET /portal)" "503 0" "tunnel down: a page"
grep -q "$CENTER_NAME" "$WORK/body" || fail "tunnel down: the fallback page"
assert_eq "$(request GET /api/portal/center-page)" "503 0" "tunnel down: an API call"
assert_match "$(cat "$WORK/body")" '"code":"SERVICE_UNAVAILABLE"' "tunnel down: JSON"
assert_eq "$(request POST /api/auth/login --data '{}')" "404 0" "tunnel down: still refused"
EDGE_PORT="$EDGE_UP"
pass "tunnel down: pages get the fallback with 503, API calls a JSON 503, the refusals hold (fails closed)"

# --- 7. the shipped examples -------------------------------------------------------------------
sed -e "s#/etc/caddy/hospital-edge#$EDGE_DIR#g" "$EDGE_DIR/Caddyfile.example" >"$WORK/Caddyfile.example"
"$CADDY_BIN" validate --adapter caddyfile --config "$WORK/Caddyfile.example" >"$WORK/validate.log" 2>&1 \
  || { cat "$WORK/validate.log" >&2; fail "caddy validate of infra/edge/Caddyfile.example"; }
pass "infra/edge/Caddyfile.example validates"

# The center-side settings of the runbook: the public name served on plain HTTP beside internal
# TLS, and only the edge's tunnel address trusted.
env CADDY_SITE_ADDRESS="hospital.lan, 192.168.1.10, http://center.example.sd" \
  CADDY_TRUSTED_PROXIES="10.213.0.1/32" APP_UPSTREAM="127.0.0.1:$UPSTREAM_PORT" \
  "$CADDY_BIN" validate --adapter caddyfile --config "$ROOT/infra/Caddyfile" >"$WORK/validate.log" 2>&1 \
  || { cat "$WORK/validate.log" >&2; fail "infra/Caddyfile with the edge settings of the runbook"; }
pass "the center's compose Caddyfile accepts the runbook's edge settings"

for f in "$EDGE_DIR"/wireguard/*.conf.template; do
  if grep -Eq '^[[:space:]]*(PrivateKey|PublicKey|PresharedKey)[[:space:]]*=[[:space:]]*[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=' "$f"; then
    fail "$f carries a real-looking WireGuard key"
  fi
done
pass "the WireGuard templates carry placeholders, never keys"

summary
