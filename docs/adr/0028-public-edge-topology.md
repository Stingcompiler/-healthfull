# 0028: How the public reaches a center: optional switches, one host, an optional edge

Date: 2026-10-29. Status: accepted (Phase 0 of `docs/PUBLIC-SITE-PLAN.md`, decided by the owner on
2026-10-29). Related: 0004 and 0005 (staff sign-in, lockout, abuse control), 0016 (portal), 0023
(center page), 0027 (marketing page), 0029 (what the public site and online booking do). Amends
ARCHITECTURE section 8 (the "no runtime fetch" rule) by one sentence, below.

Every decision here is **[SETTLED]**: the owner's own choice, or a Phase 0 recommendation the owner
accepted. The first draft of this ADR proposed a separate public listener (a second process with
only the public operations routed) as defense in depth; the owner rejected it on 2026-10-29
(decision 3 and "Alternatives rejected").

## Context
Every center install today is private: Caddy on the LAN, internal TLS, no inbound internet
(`infra/Caddyfile`, ARCHITECTURE 8). A public website and online booking need a server the
internet can reach. Two real shapes exist and both must work:

1. **An internet-facing deployment.** The OVH server already is one (`healtfull.stingdev.pro`
   production and `demo.healtfull.stingdev.pro`, a host Caddy in front of the compose `web`
   service). Staff and visitors reach the same host today.
2. **A LAN-only install.** The center's own server, no public IP, no inbound port. The public can
   reach it only if the center (or the vendor on its behalf) adds something in front.

The landing page and the booking page must be optional, because a LAN-only center that wants
neither must see no change, and an internet deployment must not publish a center that has not
filled in its page.

## Decisions

**1. [SETTLED] The application does not know how it is exposed.** Two administrator switches
decide what the public sees: `site_enabled` (the center website) and `online_booking_enabled`
(the booking page); a third, `patient_tracking_enabled`, decides the patient sign-in (model and
rules in 0029). All default **off**. On a LAN-only install, switching them on shows the pages on
the LAN only. They are enforced in services and routers, never only in the UI. How a visitor
reaches the server (public IP, host Caddy, tunnel) is infrastructure, documented in runbooks.

**2. [SETTLED] Two deployment shapes, one feature.**

| | Internet-facing (OVH) | LAN-only |
|---|---|---|
| Reach | the host's existing public name | nothing by default |
| What makes it public | nothing new: the host Caddy already proxies the whole app on that name | an **edge** (decision 5) tunnels the allowlisted public operations to the app |
| Edge needed | no | yes, only if the center wants the pages on the internet |
| Switches | the same | the same |

**3. [SETTLED] One domain, one host, one application process.** The center website, online
booking, the patient portal and the staff application are served under **one** public name by
**one** host (for example `healtfull.stingdev.pro` serves all of them). There is **no** separate
public hostname, **no** separate public listener and **no** network isolation between the public
pages and the staff app on an internet-facing deployment. Security comes from enforcement inside
the application, which every request passes through whatever the network shape:

- **Switches** (decision 1, 0029 B): a public or patient operation whose switch is off answers its
  error code (`SITE_DISABLED`, `ONLINE_BOOKING_DISABLED`, `PORTAL_DISABLED`) from the service
  layer, so a forgotten router check cannot publish it.
- **Authentication separation**: staff routers require the staff session and a permission code
  (`require_perm`); patient operations require the portal cookie (`portal_auth`, 0016); guest
  operations (0029 D) require the guest cookie. A cookie of one kind is never accepted by another
  kind of operation (matrix tests). The three staff-session operations that live in the portal
  router (`POST /api/portal/access-codes`, `GET|POST /api/portal/patients/{id}/access-codes`,
  `POST /api/portal/access-codes/{id}/revoke`, `backend/apps/portal/api.py`) keep `session_auth`
  and their permission.
- **Abuse control**: staff sign-in lockout and per-address limits (0004, 0005), portal and public
  throttles (0016, 0023), and the booking limits of 0029 F. They key on `client_ip`, which is why
  decision 6 matters on an internet-facing host.
- **The operation allowlist test stays**: `OPEN_OPERATIONS` in `backend/api/tests/test_main.py`
  lists every operation reachable without a staff session; a new public operation is private until
  it is listed there deliberately.

The staff sign-in page is therefore reachable on the internet on an internet-facing deployment, as
it already is on OVH today; that exposure is accepted and is covered by 0004 and 0005.

**Per-operation allowlist, LAN edge only (Phase 6).** The list of public operations below is kept,
but only as the configuration of the optional edge for LAN-only installs (decision 5). It is not
used on an internet-facing deployment. The edge allowlists exact paths and methods, never a prefix:

- Center site: `GET /api/portal/center-page`, `/center-identity`, `/center-logo`,
  `/center-media/{id}` (Phase 2).
- Patient portal: `GET /api/portal/session`, `POST /api/portal/login`, `POST /api/portal/session/logout`,
  `GET /api/portal/verify`, and every patient operation (`PATIENT_OPERATIONS`, `portal_auth`).
- Booking: the doctor, day and slot reads, `POST /api/portal/appointments*`, and the guest
  operations of 0029.
- `GET /api/ops/site` (the pre-render switches, ADR 0027) and `GET /api/auth/csrf` (the CSRF token
  every public POST needs, `frontend/src/lib/api/csrf.ts`), both GET only and listed as exact paths.
- **Never routed by the edge:** every other `/api/auth/*` operation, every staff router
  (`/api/visits`, `/api/core`, ...), `/admin`, and the three staff-session operations of the
  portal router named above. A prefix rule `/api/portal/*` would have exposed them; the exact list
  does not. The edge serves the SPA bundle and the public client routes (`/`, `/portal*`,
  `/verify*`, `/assets/*`, the public booking routes of 0029) and answers 404 for staff client
  routes. `infra/tests` proves the edge refuses the never-routed set (Phase 6).

**4. [SETTLED] Root `/` precedence: the center website wins.** One deployment can hold two kinds
of public page: the center's website (0029) and the vendor's sales page (`MARKETING_SITE`, 0027).
They are different things. At the exact path `/`:

| Order | Condition | `/` shows |
|---|---|---|
| 1 | a staff session exists | the dashboard (unchanged) |
| 2 | `site_enabled` is on | the center website (the same component as `/portal`) |
| 3 | `MARKETING_SITE` is on | the vendor sales page (0027 addendum) |
| 4 | otherwise | redirect to the staff sign-in (`/login`) |

`/login` is untouched: the sales page while `MARKETING_SITE` is on, the plain staff sign-in
otherwise. `/sign-in` stays the staff sign-in. `/portal` keeps working as the same center page, so
printed slips stay valid. A deployment that is both a vendor sales host and a center (for
example the OVH production while it has no center of its own) therefore shows the center site at
`/` once an administrator switches it on and keeps the sales page at `/login`; an operator who
wants the sales page at `/` leaves `site_enabled` off. The SPA learns the switch before first
render from `GET /api/ops/site`, which gains a boolean `center_site` (public, no session, same
failure rule as 0027: an unreachable server leaves it off). The center website carries a small
"Staff sign-in" link that goes to `signInPath()`.

**5. [SETTLED, recommended mechanism] The edge exists for LAN-only installs.** The center's server
opens an outbound tunnel (WireGuard to a vendor-run VPS is the recommended mechanism: no third
party; a managed tunnel such as Cloudflare Tunnel also works and is the owner's call on trust and
cost). The server initiates, so there is no inbound port, no public IP and no router change. The
edge is a Caddy on the VPS that proxies the tunnel **for the allowlisted operations of decision 3
only**, adds rate limits and TLS, and serves a static fallback (center name, phone, "online booking
temporarily unavailable") from a cached copy of the center page when the tunnel is down. It fails
closed: with the tunnel down nothing else is reachable. The edge is opt-in per center, delivered in
Phase 6, and is **not used** on an internet-facing deployment, where the host's own name already
serves the whole app (decision 3).

**[DECIDED 2026-10-29, owner] Tunnel provider: WireGuard to the vendor's OVH host.** For a
LAN-only install that wants the public site, the center's server opens a WireGuard tunnel to the
vendor's existing OVH host, whose Caddy is the edge of this decision. No managed third-party
tunnel (Cloudflare Tunnel or similar) is used. Built in Phase 6; nothing changes before then.
This closes open item 2 of `docs/inspection/public-site-impact.md`.

ARCHITECTURE section 8 is amended by this sentence: *the application itself makes no outbound
request; an optional tunnel process outside the application may carry inbound traffic to it.* The
rule "no runtime internet dependency" is otherwise unchanged: the pages work on the LAN with the
tunnel absent.

**6. The client address behind proxies must be right, or every per-address limit is wrong.** The
limits of 0005, 0016, 0023 and 0029 key on `apps.core.services.client_ip`, which trusts
`X-Forwarded-For` only when `DJANGO_TRUST_X_FORWARDED_FOR=1`, and then takes the **leftmost**
entry. Behind two proxies (host Caddy, then the compose Caddy) a proxy that appends instead of
overwriting lets a visitor choose the leftmost value, and a proxy that overwrites without trusting
the first hop makes all visitors one address. This ADR requires, for any internet-facing deployment
and for the edge: the outermost proxy **overwrites** the header with the connection address, inner
proxies trust only that hop (`trusted_proxies`), the app sets the trust flag, and a runbook check
(a request with a forged header is counted under the real address) proves it before the public
switches are turned on. **Not verified here:** the current OVH host Caddy configuration was not read
(no server access in Phase 0 or Phase 1); the owner, or a session with server access, must check it
before switching `site_enabled` or `online_booking_enabled` on there.

**7. Failure behavior.** One process serves everything, so an application or database outage takes
the public pages and the staff app down together, exactly as today; the SPA shows its offline
state. On a LAN install with an edge, a tunnel outage shows the edge fallback page to the public
while staff on the LAN are unaffected.

## Alternatives rejected
- **A separate public listener** (a second process of the same image whose URL configuration routes
  only the public operations, reached through a second public name). It isolates staff routes from
  the internet at the network level, but on the OVH host it adds a second name, a second process
  and a second Caddy site block for a staff app that is already internet-facing and protected by
  sign-in lockout and permissions. Rejected by the owner on 2026-10-29 in favour of decision 3. The
  same isolation is still available to a LAN-only install through the edge allowlist.
- **A separate public service with a replicated read model and a booking queue** (plan D1
  alternative). It survives outages but needs a second deployable, a sync protocol and conflict
  handling, and bookings become "pending until synced" with no real availability. Rejected for V1.
- **A path-prefix allowlist at the edge** (`/api/portal/*`). It exposes the staff-session portal
  operations; the edge uses exact paths (decision 3).
- **Port-forwarding the center's own IP.** Needs a static address and router access most Sudanese
  centers do not have, and exposes the whole server.

## Consequences
- No new process, port or Caddy site block for an internet-facing deployment; `infra/` is
  unchanged by Phases 1 to 5. Phase 6 adds `infra/edge/` and its runbook for LAN installs.
- Phase 1 builds the switches, their service-level guards and tests (every public and patient
  operation with each switch off answers the exact code), `GET /api/portal/center-identity`, and
  `center_site` in `GET /api/ops/site` with the root precedence of decision 4. It builds **no**
  public listener and no `urls_public.py`.
- `GET /api/ops/site` gains `center_site`; `frontend/src/lib/site.ts`, `src/app/routes.tsx` and
  their tests change (`docs/inspection/public-site-impact.md`).
- Owner action before switching the public pages on at OVH: verify the header handling of
  decision 6 on the host Caddy.

## Implementation note: decision 6 (2026-10-29)
The OVH host Caddy turned out to be a bare `reverse_proxy 127.0.0.1:8300`: it overwrites
`X-Forwarded-For` with the visitor's address (correct for the outermost hop), but the compose Caddy
trusted no peer and overwrote it again with the Docker gateway address, so every internet visitor
reached Django as one address. Fixed in two places:
- **Compose Caddy** (`infra/Caddyfile`): global `servers { trusted_proxies static
  {$CADDY_TRUSTED_PROXIES} }`, passed through `infra/docker-compose.yml`. Empty (the default, valid
  Caddy that trusts nobody) keeps the LAN behavior: the compose Caddy is the edge and replaces any
  forged header. Behind a host proxy with `BIND_IP=127.0.0.1`, `CADDY_TRUSTED_PROXIES=private_ranges`
  keeps the host proxy's header and appends the gateway. Proven by
  `infra/tests/test_caddy_trusted_proxies.sh` (`caddy validate` of each form, then real requests;
  the CI docker job runs it with the web image's own Caddy binary).
- **Django** (`apps.core.services.client_ip`): with `DJANGO_TRUST_X_FORWARDED_FOR=1` the header is
  now read from the **right**, skipping `DJANGO_TRUSTED_PROXIES` (default `private_ranges`), instead
  of taking the leftmost entry. A forged leading entry can then never win, even if some proxy in the
  chain appends rather than overwrites; when every entry is a private hop (a LAN client), the
  leftmost is used, which the compose Caddy wrote itself. A malformed entry ends the walk.
Runbook: `docs/runbooks/install.md` "Behind a host reverse proxy".

## Phase 6 as built (2026-10-30): the LAN edge
- **Shape.** `infra/edge/edge.caddy` is a directive file the vendor host's existing Caddy imports
  inside one site block per center (`import .../edge.caddy <tunnel addr:port> <fallback dir>
  "<name>" "<phone>"`, Caddy 2.7 or later; example `infra/edge/Caddyfile.example`). One host,
  one Caddy, the host's other sites untouched (decision 3 applies to the app; the edge is the
  per-center public name of decision 5).
- **Allowlist, exact paths and methods (decision 3).** One CEL expression: GET
  `/api/auth/csrf`, `/api/ops/site`, the public center-site, booking-read, challenge, session,
  verify and patient reads, `/api/portal/guest/booking`; POST session, logout, appointments,
  notices, guest booking, guest sign-in, sign-out, cancel and reschedule; parameterized paths as
  anchored regexes with digit ids. 39 API operations: every `/api/portal` operation whose security
  is none, `PortalAuth` or `GuestAuth`, plus the two plumbing reads. Pages: GET/HEAD `/`,
  `/portal`, `/portal/*`, `/verify/*`, `/assets/*` and the named root files of the build. The
  decision text's `POST /api/portal/login` does not exist; patient sign-in is `POST
  /api/portal/session`.
- **Refusals.** Other API paths: `404 {"code": "NOT_FOUND"}` from the edge; other pages: the
  fallback page with 404; raw paths with `%`, a dot segment, `//` or `\` refused before routing;
  bodies over 256 KB 413. **`GET /api/auth/me` answers `401 NOT_AUTHENTICATED` at the edge**
  without reaching the center: the SPA asks it at `/` to tell a visitor from staff
  (`frontend/src/app/routes.tsx`), and a 404 there would break the center website at `/`.
- **Fallback (decision 5), deviation.** A static self-contained page (`infra/edge/fallback/`,
  Caddy `templates`) with the name and phone given in the import line, Arabic first, under a
  `default-src 'none'` CSP; not a cached copy of the center page (no sync job, nothing to go
  stale). Shown with 503 when the tunnel or the center is down (dial failure, or the center's
  502/503/504 on a page); API calls then answer `503 {"code": "SERVICE_UNAVAILABLE"}`.
- **No rate limit at the edge, deviation.** Stock Caddy has no rate-limit module and the vendor
  host runs the stock build. The application's per-address limits (0005, 0016, 0023, 0029 F)
  apply and see the real address through the chain below.
- **X-Forwarded-For (decision 6).** The host Caddy trusts no proxy, so `reverse_proxy` overwrites
  the header (and `X-Forwarded-Proto`) with what it saw; the center's compose Caddy trusts only the
  edge's tunnel address (`CADDY_TRUSTED_PROXIES=10.213.0.1/32`) and appends it; Django skips it
  as a private hop. The tunnel network is `10.213.0.0/24` so that hop is in `private_ranges`.
  HSTS on the edge keeps browsers from sending the center's (non-Secure, plain-HTTP LAN) cookies
  over plain HTTP to the public name.
- **Tunnel (decision 5).** WireGuard interface `hs-edge`, `wg-quick@hs-edge`. Templates with
  placeholders only: `infra/edge/wireguard/edge-host.conf.template` (drops anything a center sends
  to the host or another center) and `center-server.conf.template` (the center dials out with
  `PersistentKeepalive`; through the tunnel only the web port is open, via `INPUT` and
  `DOCKER-USER` rules), plus the systemd drop-in `wg-quick-after-docker.conf`. The center must
  publish `web` on `BIND_IP=0.0.0.0` (a LAN-address bind never answers the tunnel; Docker's DNAT
  keeps the edge's source address, the userland proxy would not).
- **Proof.** `infra/tests/test_edge_allowlist.sh` (in `infra/tests/run.sh`; the CI docker job
  runs it with the web image's Caddy): every operation of `frontend/openapi.json` sent through
  the edge is forwarded if and only if it is in the derived set; the staff surface by name
  (`/api/auth/*`, `/api/visits/*`, `/administration*`, `/sign-in`, `/login`, `/admin`, `/static`,
  staff screens, the staff-session portal operations); wrong methods; encoded and dot-segment
  paths; forwarded pages and files; Host, path and query kept; forged `X-Forwarded-For` and
  `X-Forwarded-Proto` overwritten; the body limit; the fallback page; tunnel down and center down;
  the example host Caddyfile and the center-side settings validate; no real-looking key in the
  templates. Runbook: `docs/runbooks/public-edge.md`.

## Code
Phase 1: `backend/apps/core/{models,services,api,schemas}.py` (`PublicSiteSettings`),
`backend/apps/ops/{api,schemas}.py`, `backend/apps/portal/{api,services,conf}.py`,
`frontend/src/lib/site.ts`, `frontend/src/app/routes.tsx`. Phase 6: `infra/edge/`
(`edge.caddy`, `Caddyfile.example`, `fallback/index.html`, `wireguard/`),
`docs/runbooks/public-edge.md`, `infra/tests/test_edge_allowlist.sh`.
