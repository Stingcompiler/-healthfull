# Public site on the internet: the edge — الموقع العام على الإنترنت

For whoever puts a center's website, online booking and patient portal on the internet, and for
the vendor who runs the internet-facing host. Rules: ADR 0028 (topology, decisions 2, 3, 5, 6) and
ADR 0029 (what the public pages do). Files: `infra/edge/`. Test: `infra/tests/test_edge_allowlist.sh`.
User guides: [online bookings (reception)](../guides/online-bookings.md),
[public site settings (administrator)](../guides/public-site.md).

## Which case is yours — أي حالة تخصك

| The server | To show the pages to the public | Edge needed |
|---|---|---|
| Internet-facing (the OVH host: `healtfull.stingdev.pro`, `demo.healtfull.stingdev.pro`) | switch them on in **Administration > Public site** (`/administration/public-site`) after the check in [Internet-facing server](#internet-facing-server-no-edge--خادم-متصل-بالإنترنت-دون-بوابة) | **no** |
| A center's own server on its LAN, pages wanted on the LAN only | the same switches; nothing else | no |
| A center's own server on its LAN, pages wanted on the internet | the switches **and** the edge below | **yes** |

The application does not know how it is reached (ADR 0028 decision 1). The three switches
(center website, online booking, patient sign-in) are enforced by the server in every case; the
edge only decides which requests from the internet reach a LAN server at all.

## How the edge works — كيف تعمل البوابة

```
visitor ── HTTPS ──> center.example.sd  (vendor's OVH host: its Caddy imports infra/edge/edge.caddy;
                                         TLS, exact path allowlist, fallback page)
                          │ WireGuard, started by the center's server (10.213.0.1 -> 10.213.0.2)
                          v
                     center server :80  (compose `web` Caddy -> `app` Django) ── LAN staff, unchanged
```

- The center's server **dials out** to the vendor's host (WireGuard, UDP 51820). No inbound port,
  no public address and no router change at the center. Nothing inside the application makes an
  outbound request (ADR 0028, ARCHITECTURE 8 as amended).
- The edge is a block in the vendor host's existing Caddy, one per center, under its own public
  name. It never changes the host's other sites.
- **Fails closed.** Tunnel or center down: pages show the fallback page (center name, phone,
  "not available right now") with 503, API calls a JSON 503. Nothing else becomes reachable.
- LAN staff are unaffected by anything here: they keep using the server's LAN name.

## What is exposed — ما المكشوف للعامة

Exact paths and methods, never a prefix (ADR 0028 decision 3). The list is the API contract's
`/api/portal` operations that are public or authenticate a patient or a guest, plus two plumbing
reads; the infra test sends **every** operation of `frontend/openapi.json` through the edge and
fails if anything else passes or one of these is missing.

| Group | Method and path |
|---|---|
| Plumbing | `GET /api/auth/csrf` (CSRF cookie for every public POST), `GET /api/ops/site` (the switches, read before the first render) |
| Center website | `GET /api/portal/center-page`, `/center-identity`, `/center-logo`, `/center-media/{id}` |
| Booking reads | `GET /api/portal/doctors`, `/doctors/{id}/days`, `/doctors/{id}/slots`, `/challenge` |
| Guest booking | `POST /api/portal/guest-bookings`, `/guest-bookings/sign-in`, `/guest/sign-out`, `/guest/booking/cancel`, `/guest/booking/reschedule`; `GET /api/portal/guest/booking` |
| Patient sign-in | `GET` and `POST /api/portal/session`, `POST /api/portal/session/logout`; receipt check `GET /api/portal/verify` |
| Patient (portal cookie) | `GET /api/portal/me`, `/summary`, `/appointments`, `/balance`, `/invoices`, `/invoices/{id}`, `/receipts`, `/receipts/{id}`, `/results`, `/results/{id}`, `/prescriptions`, `/visits`, `/visits/{id}/timeline`, `/notices`; `POST /api/portal/appointments`, `/appointments/{id}/cancel`, `/appointments/{id}/reschedule`, `/notices/{id}/read`, `/notices/read-all` |
| Pages and files (`GET`, `HEAD`) | `/`, `/portal`, `/portal/*`, `/verify/*`, `/assets/*`, `/index.html`, `/boot.js`, `/favicon.svg`, `/robots.txt`, `/portal.webmanifest`, `/portal-icon-192.png`, `/portal-icon-512.png`, `/portal-icon-maskable-512.png` |

`{id}` is digits only. 39 API operations in all (the test prints the count).

**Never forwarded:** every other `/api/auth/*` (staff sign-in, sign-out, password, preferences),
every staff router (`/api/visits/*` including the online bookings inbox, `/api/core/*`,
`/api/billing/*`, ...), `/api/ops/health` and `/status`, the staff-session portal operations
(`/api/portal/access-codes*`, `/api/portal/patients/{id}/access-codes`, `/api/portal/ping`),
Django admin `/admin`, `/static`, every staff screen (`/sign-in`, `/login`, `/administration*`,
`/queue`, `/patients`, ...), any other method on an allowed path, and any raw path with `%`, a
dot segment, `//` or a back slash. Refused API calls answer `404 {"code": "NOT_FOUND"}`; refused
pages answer the fallback page with 404. `GET /api/auth/me` answers `401 NOT_AUTHENTICATED` from
the edge itself (the SPA asks it at `/` to tell a visitor from signed-in staff; there is no staff
session through the edge). Bodies over 256 KB are refused (413).

Honest limits:
- The SPA bundle is the same file for staff and public, so a visitor's browser can draw the staff
  sign-in screen (for example `/` with the website switched off). It cannot do anything: every
  staff call is refused at the edge.
- No rate limit at the edge (the stock Caddy has none). The application's own per-address limits
  apply (sign-in lockout, portal, page and booking caps, ADR 0016, 0023, 0029 F); they key on the
  real visitor address, which is why the X-Forwarded-For settings below matter.
- The center's cookies are not marked `Secure` on a plain-HTTP LAN install. The edge always uses
  HTTPS and sends HSTS, so browsers never send them to the public name over plain HTTP.
- The website is down whenever the center's internet is down (fallback page only).
- The fallback page shows the name and phone given in the edge block, not a copy of the center
  page.

## Enable for a LAN center — التشغيل لمركز داخل الشبكة

Owner steps, in order. Placeholders: `center.example.sd` (the public name), `10.213.0.2` (this
center's tunnel address; the vendor host is `10.213.0.1`, each center the next free address),
`203.0.113.10` (the vendor host's public address).

### 1. Before you start

- The center's server runs the stack (`docs/runbooks/install.md`) on a version that has the
  public site (ADR 0029). `HTTP_PORT` below is the one in its `.env` (default 80).
- The vendor host: Caddy 2.7 or later (`caddy version`), `wireguard-tools`, UDP 51820 open in its
  firewall (OVH network firewall too, if enabled).
- DNS: an `A` record `center.example.sd -> 203.0.113.10` (the owner or the center's domain
  holder). Caddy gets the certificate itself once the record resolves.
- Both machines: `sudo apt install wireguard-tools`.

### 2. Keys (never in the repository, never in chat)

```bash
# on the center's server
sudo -i
umask 077 && cd /etc/wireguard
wg genkey | tee center.key | wg pubkey > center.pub    # send center.pub to the vendor
# on the vendor host, once for the host and once per center
umask 077 && cd /etc/wireguard
[ -f edge.key ] || { wg genkey | tee edge.key | wg pubkey > edge.pub; }
wg genpsk > center-one.psk                              # give it to the center by hand, once
```

### 3. Vendor host: the tunnel

1. Copy `infra/edge/wireguard/edge-host.conf.template` to `/etc/wireguard/hs-edge.conf`
   (mode 0600) and replace each `<...>`: the host's private key, then one `[Peer]` per center
   (its public key, the preshared key, `AllowedIPs = 10.213.0.2/32`, a single address).
2. `sudo systemctl enable --now wg-quick@hs-edge`. Adding a center later: edit the file, then
   `sudo wg syncconf hs-edge <(sudo wg-quick strip hs-edge)` (no restart, other centers keep
   their tunnel).

The template's rules drop anything a center sends to the host or towards another center; only
answers to the edge's own connections come back.

### 4. Center server: the tunnel

1. Copy `infra/edge/wireguard/center-server.conf.template` to `/etc/wireguard/hs-edge.conf`
   (mode 0600): its address, its private key, the host's public key, the preshared key and
   `Endpoint = 203.0.113.10:51820`. If `HTTP_PORT` is not 80, change the `--ctorigdstport 80`
   rule (both lines).
2. Start it after Docker:
   ```bash
   sudo install -D -m 0644 infra/edge/wireguard/wg-quick-after-docker.conf \
     /etc/systemd/system/wg-quick@hs-edge.service.d/10-after-docker.conf
   sudo systemctl daemon-reload && sudo systemctl enable --now wg-quick@hs-edge
   sudo wg show hs-edge            # "latest handshake: ... seconds ago"
   ```

The template lets the edge open the web port through the tunnel and nothing else (not SSH, not
the database, not 443).

### 5. Center server: `.env`

| Setting | Value | Why |
|---|---|---|
| `BIND_IP` | `0.0.0.0` | Docker must publish `web` on the tunnel address too. A LAN-address-only bind never answers the tunnel. The tunnel rules above already limit what arrives on it; if the server also has a WAN or 4G interface, close it with a persistent `DOCKER-USER` rule (install.md "Firewall and Docker"). |
| `CADDY_TRUSTED_PROXIES` | `10.213.0.1/32` | Keep the visitor address the edge wrote (ADR 0028 decision 6). Only the edge's one tunnel address, never a range: no LAN machine can use it (answers to it route into the tunnel, and WireGuard accepts it only from the edge's key). This is the one exception to install.md's "never set it when `web` is on the LAN". |
| `DJANGO_ALLOWED_HOSTS` | add `center.example.sd` | The edge keeps the visitor's `Host`. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | add `https://center.example.sd` | Public sign-in and booking are POSTs from that origin. |
| `DJANGO_TRUST_X_FORWARDED_FOR`, `DJANGO_TRUST_X_FORWARDED_PROTO` | `1` (the defaults of `.env.example`) | Django reads the visitor address from the right and knows the visitor used HTTPS. |
| `DJANGO_TRUSTED_PROXIES` | unset (`private_ranges`) | Skips the tunnel hop `10.213.0.1`; this is why the tunnel network is inside `10.0.0.0/8`. |
| `CADDY_SITE_ADDRESS` | `:80` needs nothing; with internal TLS (`hospital.lan, 192.168.1.10`) append `, http://center.example.sd` | The edge reaches `web` on plain HTTP inside the encrypted tunnel, with the public name as `Host`. |

Then `infra/compose.sh up -d` (recreates `web` and `app`, no rebuild) and check
`sudo ss -ltnp | grep ':80 '` shows `0.0.0.0:80`.

### 6. Vendor host: the edge in Caddy

```bash
sudo install -d /etc/caddy/hospital-edge/fallback
sudo install -m 0644 infra/edge/edge.caddy /etc/caddy/hospital-edge/edge.caddy
sudo install -m 0644 infra/edge/fallback/index.html /etc/caddy/hospital-edge/fallback/index.html
```

Add the center's block from `infra/edge/Caddyfile.example` to `/etc/caddy/Caddyfile`, below the
host's existing sites, which stay as they are:

```
center.example.sd {
	import /etc/caddy/hospital-edge/edge.caddy 10.213.0.2:80 /etc/caddy/hospital-edge/fallback "اسم المركز" "+249 9xx xxx xxx"
}
```

The host Caddyfile must have **no** global `servers { trusted_proxies ... }`: the edge is the
outermost proxy and must overwrite `X-Forwarded-For` with the visitor's address. Then:

```bash
sudo caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Use `edge.caddy` from the newest release in use: an operation an older center does not have is
answered 404 by that center.

### 7. Switch the pages on

In the center's system: **Administration > Public site** (`/administration/public-site`), see the
[administrator guide](../guides/public-site.md). Then run [Verify](#verify--التحقق).

## Verify — التحقق

From a machine **outside** the center (a phone on mobile data, or any internet machine):

```bash
H=https://center.example.sd
for p in / /portal /portal/book /api/ops/site /api/portal/center-identity; do
  printf '%-32s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "$H$p")"; done    # all 200
for p in /sign-in /login /administration /admin/ /api/ops/health /api/visits/online-bookings /api/core/center/logo; do
  printf '%-32s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "$H$p")"; done    # all 404
curl -s -o /dev/null -w '%{http_code}\n' -X POST "$H/api/auth/login"                   # 404
curl -s "$H/api/auth/me"                                                                # 401 NOT_AUTHENTICATED
```

`/api/portal/center-identity` answers 200 even with the website off; `/api/ops/site` shows which
switches are on.

**The visitor address (ADR 0028 decision 6), before telling anyone the address.** From outside,
with online booking on, send one wrong guest sign-in with a forged header:

```bash
curl -s -c /tmp/edge.jar -o /dev/null "$H/api/auth/csrf"
T="$(awk '$6 == "csrftoken" {print $7}' /tmp/edge.jar)"
curl -s -b /tmp/edge.jar -H "X-CSRFToken: $T" -H "Referer: $H/portal/booking" \
  -H 'Content-Type: application/json' -H 'X-Forwarded-For: 203.0.113.7' \
  -X POST "$H/api/portal/guest-bookings/sign-in" -d '{"reference":"AAAAAAAAAA","pin":"000000"}'
# {"code": "GUEST_INVALID_CREDENTIALS", ...}
```

On the center's server:

```bash
infra/compose.sh exec -T app python manage.py shell -c "from apps.portal.models import PortalEvent; [print(e.created_at, e.kind, e.ip_address) for e in PortalEvent.objects.order_by('-id')[:3]]"
```

The `guest_view_refused` line must show the outside machine's own public address: not
`203.0.113.7` (forged), not `10.213.0.1` (`CADDY_TRUSTED_PROXIES` missing), not `172.x.x.x`
(Docker's gateway: `BIND_IP` or the userland proxy is in the way).

**Fails closed.** On the center's server `sudo systemctl stop wg-quick@hs-edge`; `$H/portal`
shows the fallback page (the center's name and phone) and `curl -s "$H/api/ops/site"` answers
`SERVICE_UNAVAILABLE`. `sudo systemctl start wg-quick@hs-edge` brings it back.

**The edge file itself.** Before installing a changed `edge.caddy`, in the repository:
`bash infra/tests/test_edge_allowlist.sh` (needs `caddy` on `PATH` or `CADDY_BIN`; CI runs it with
the web image's Caddy).

## Disable — الإيقاف

- **Hide the pages, keep the edge:** switch the website, online booking and patient sign-in off
  in `/administration/public-site`. The server then answers `SITE_DISABLED`,
  `ONLINE_BOOKING_DISABLED`, `PORTAL_DISABLED`; patient sessions end.
- **Remove the edge:** on the vendor host delete the center's block from `/etc/caddy/Caddyfile`
  and `sudo systemctl reload caddy`; remove its `[Peer]` from `/etc/wireguard/hs-edge.conf` and
  `sudo wg syncconf hs-edge <(sudo wg-quick strip hs-edge)`. On the center's server
  `sudo systemctl disable --now wg-quick@hs-edge`, then in `.env` empty `CADDY_TRUSTED_PROXIES`,
  set `BIND_IP` back to the LAN address, remove the public name from `DJANGO_ALLOWED_HOSTS`,
  `DJANGO_CSRF_TRUSTED_ORIGINS` and `CADDY_SITE_ADDRESS`, and `infra/compose.sh up -d`.
- **Emergency (suspected abuse):** on the vendor host replace the center's `import` line with
  `respond 503` and reload Caddy, or `sudo wg set hs-edge peer <CENTER_PUBLIC_KEY> remove`. Either
  takes effect at once and touches no other center.

## Rotate keys — تدوير المفاتيح

Rotate once a year, when someone who held a key leaves, when a server is replaced, and at once
if a key may have leaked. TLS certificates renew themselves.

- **A center's key:** on the center's server make a new pair (step 2), put the new private key
  in its `hs-edge.conf`; on the vendor host replace that peer's `PublicKey` and
  `sudo wg syncconf hs-edge <(sudo wg-quick strip hs-edge)`; then on the center
  `sudo systemctl restart wg-quick@hs-edge` and check `wg show` for a fresh handshake. The
  public pages are away for under a minute.
- **The preshared key:** `wg genpsk` on the vendor host, set it on both sides the same way.
- **The vendor host's key** (affects every center): make the new pair, then for each center set
  the new `PublicKey` in its `[Peer]` and restart its tunnel right after the host switches
  (`PrivateKey` in the host file, `wg syncconf`). Plan it with the centers; each is away until
  its side is updated.
- Delete old key files (`shred -u`) after the handshake works.

## Internet-facing server (no edge) — خادم متصل بالإنترنت دون بوابة

The OVH deployments are already reachable from the internet under one name; the website, online
booking, the portal and the staff application share it (ADR 0028 decision 3). No edge and no
WireGuard: the public pages appear when the administrator switches them on. The staff sign-in is
reachable there as it always was; the lockout and per-address limits protect it (ADR 0004, 0005).

Before the first switch is turned on, once per server:

1. The X-Forwarded-For chain (ADR 0028 decision 6): host Caddy overwrites, `web` trusts the
   Docker network (`CADDY_TRUSTED_PROXIES=private_ranges`, `BIND_IP=127.0.0.1`), Django reads from
   the right. Steps and check: install.md
   ["Behind a host reverse proxy"](install.md#behind-a-host-reverse-proxy--خلف-وكيل-عكسي-على-الخادم).
   The forged-header check in [Verify](#verify--التحقق) works there as well (the line must not
   show `172.x.x.x`).
2. `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` carry the public name (already true
   on a working deployment).
3. Switch on in `/administration/public-site`; `curl -s https://<name>/api/ops/site` shows them.

Turning off: the same switches. On a server that is also the vendor's sales site
(`MARKETING_SITE=1`), the center website takes `/` once switched on and the sales page stays at
`/login` (ADR 0028 decision 4).

## Troubleshooting — حل المشاكل

| Symptom | Cause | Do |
|---|---|---|
| Every page shows the fallback page (503) | no tunnel | `sudo wg show hs-edge` on both sides: no handshake = UDP 51820 blocked, wrong endpoint or key; a handshake but still 503 = `BIND_IP` not `0.0.0.0`, the `--ctorigdstport` rule not `HTTP_PORT`, or `web` down (`infra/compose.sh ps`) |
| `Bad Request (400)` | `DJANGO_ALLOWED_HOSTS` lacks the public name | add it, `infra/compose.sh up -d` |
| Sign-in or booking fails with a CSRF error (403) | `DJANGO_CSRF_TRUSTED_ORIGINS` lacks `https://<name>`, or `X-Forwarded-Proto` lost (`CADDY_TRUSTED_PROXIES` empty) | set both, `up -d` |
| Every visitor has the address `10.213.0.1` | `CADDY_TRUSTED_PROXIES` empty | set `10.213.0.1/32`, `up -d web` |
| Visitors have `172.x.x.x` | the connection reaches `web` through Docker's userland proxy | keep `BIND_IP=0.0.0.0` (Docker's DNAT keeps the source); check `ss -ltnp` |
| A public page answers 404 at the edge | the page or call is not in the allowlist (a newer release added it) | install the newest `edge.caddy`, reload Caddy |
| Caddy refuses to load (`{args[0]}`) | Caddy older than 2.7 on the host | update Caddy on the host |
| The site works on the LAN but not outside | DNS not pointing at the host, or the certificate not issued yet | `dig +short <name>`; `sudo journalctl -u caddy --since -10min` |
