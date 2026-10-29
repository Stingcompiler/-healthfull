# 0028: How the public reaches a center: optional switches, a public listener, an optional edge

Date: 2026-10-29. Status: proposed (Phase 0 of `docs/PUBLIC-SITE-PLAN.md`, awaiting the owner's
review). Related: 0005 (one door, abuse control), 0016 (portal), 0023 (center page), 0027
(marketing page), 0029 (what the public site and online booking do). Amends ARCHITECTURE section 8
(the "no runtime fetch" rule) by one sentence, below.

Items marked **[DESIGN DECISION, owner may veto]** are recommendations adopted from the Phase 0
review, not choices the owner has already made. The owner's settled choices are marked
**[SETTLED]**. Everything else follows from them.

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
| Reach | the host's public name | nothing by default |
| What makes it public | the host Caddy exposes the **public listener** (decision 3) on a public name | an **edge** (decision 5) tunnels to the public listener |
| Edge needed | no | yes, only if the center wants the pages on the internet |
| Switches | the same | the same |

**3. [DESIGN DECISION, owner may veto] A separate public listener inside the app, defense in
depth.** The app can run a second listener whose URL configuration contains **only** the
allowlisted public operations; every other path answers the JSON `404 NOT_FOUND`. Staff session
cookies are never read on it (a staff request that reaches it is anonymous). It shares the
database and the code with the staff listener; it is a second process of the same image, enabled
by `PUBLIC_LISTENER_PORT` (unset = no public listener, which is the default and the LAN-only
behavior). A host Caddy, a tunnel or an edge points a public name at this listener and never at
the staff listener. A mistake in the proxy's path list then cannot expose staff routes, because
the process behind it does not have them.

The allowlist is a list of operation ids, enforced by a test that enumerates every operation of
the full API and asserts that the public URL configuration routes exactly the listed set (a new
operation is private until someone lists it, the same shape as `OPEN_OPERATIONS` in
`backend/api/tests/test_main.py`). Planned set (Phase 1 builds the mechanism, later phases add
their operations):

- Center site: `GET /api/portal/center-page`, `/center-identity`, `/center-logo`,
  `/center-media/{id}`.
- Patient portal: `GET /api/portal/session`, `POST /api/portal/login`, `POST /api/portal/session/logout`,
  `GET /api/portal/verify`, and every patient operation (`PATIENT_OPERATIONS`, `portal_auth`).
- Booking: the doctor, day and slot reads (currently `/api/portal/doctors*`, patient-session
  only), `POST /api/portal/appointments*`, and the guest operations of 0029.
- `GET /api/ops/site` (the pre-render switches, ADR 0027), method GET only.
- A CSRF token: today the SPA fetches `GET /api/auth/csrf`. The public listener must not route
  the `auth` namespace; Phase 1 adds `GET /api/portal/csrf` with the same behavior and the portal
  client uses it.
- **Never routed there:** `/api/auth/*`, every staff router (`/api/visits`, `/api/core`, ...),
  `/admin`, and the three **staff-session operations that live in the portal router**
  (`POST /api/portal/access-codes`, `GET|POST /api/portal/patients/{id}/access-codes`,
  `POST /api/portal/access-codes/{id}/revoke`, `backend/apps/portal/api.py` lines 232-330). A
  path allowlist written as `/api/portal/*` would have exposed them; the per-operation allowlist
  does not.

The SPA bundle is static and public by nature. The public site block serves the bundle and the
public client routes (`/`, `/portal*`, `/verify*`, `/assets/*`, the public booking routes of
0029); a staff client route on the public name answers 404 rather than the app shell.

**4. [DESIGN DECISION, owner may veto] Root `/` precedence: the center website wins.** One
deployment can hold two kinds of public page: the center's website (0029) and the vendor's sales
page (`MARKETING_SITE`, 0027). They are different things. At the exact path `/` for a visitor with
no staff session:

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
edge is a Caddy on the VPS that proxies the tunnel to the **public listener only**, adds
rate limits and TLS, and serves a static fallback (center name, phone, "online booking
temporarily unavailable") from a cached copy of the center page when the tunnel is down. It fails
closed: with the tunnel down nothing else is reachable. The edge is opt-in per center, delivered in
Phase 6, and is **not needed** on an internet-facing deployment, which points its host Caddy at
the public listener directly.

ARCHITECTURE section 8 is amended by this sentence: *the application itself makes no outbound
request; an optional tunnel process outside the application may carry inbound traffic to it.* The
rule "no runtime internet dependency" is otherwise unchanged: the pages work on the LAN with the
tunnel absent.

**6. The client address behind proxies must be right, or every per-address limit is wrong.** The
limits of 0005, 0016 and 0023 key on `apps.core.services.client_ip`, which trusts
`X-Forwarded-For` only when `DJANGO_TRUST_X_FORWARDED_FOR=1`, and then takes the **leftmost**
entry. Behind two proxies (host Caddy, then the compose Caddy) a proxy that appends instead of
overwriting lets a visitor choose the leftmost value, and a proxy that overwrites without trusting
the first hop makes all visitors one address. This ADR requires, for any deployment with the
public listener: the outermost proxy **overwrites** the header with the connection address, inner
proxies trust only that hop (`trusted_proxies`), the app sets the trust flag, and a Phase 1 test
and a runbook check (a request with a forged header is counted under the real address) prove it.
**Not verified here:** the current OVH host Caddy configuration was not read (no server access in
Phase 0); Phase 1 must check it before the public switches are turned on there.

**7. Failure behavior.** Public listener down: the proxy answers 502 and the SPA shows its
offline state; staff work is unaffected (separate process). Tunnel down: edge fallback page.
Database down: both listeners fail health checks the same way. The public listener has its own
health route for the proxy and never reports staff detail.

## Alternatives rejected
- **A separate public service with a replicated read model and a booking queue** (plan D1
  alternative). It survives outages but needs a second deployable, a sync protocol and conflict
  handling, and bookings become "pending until synced" with no real availability. Rejected for V1.
- **A path allowlist at the proxy only.** One layer; a typo exposes staff routes. Kept as the
  outer layer, not the only one.
- **Port-forwarding the center's own IP.** Needs a static address and router access most Sudanese
  centers do not have, and exposes the whole server.

## Consequences
- New settings: `PUBLIC_LISTENER_PORT`, plus the compose service and a Caddy public site block
  (`CADDY_PUBLIC_ADDRESS`, empty = none). `.env.example` and `docs/runbooks/install.md` change.
- Tests added in Phase 1: public URL configuration equals the allowlist; a staff cookie on the
  public listener is ignored; every non-listed path is 404; the forged-`X-Forwarded-For` case.
  Phase 6 adds the edge-config test (`infra/tests`).
- `GET /api/ops/site` gains `center_site`; `frontend/src/lib/site.ts`, `src/app/routes.tsx` and
  their tests change (`docs/inspection/public-site-impact.md`).
- Open question for the owner: on the OVH host staff and visitors share one name today. Do you want
  the center website on that same name (then the staff listener stays reachable there, the public
  listener adds no isolation on that host) or on a second public name that points at the public
  listener only? The design supports both; the second gives the isolation of decision 3.

## Code (planned)
`backend/config/urls_public.py`, `backend/apps/ops/{api,schemas}.py`, `infra/docker-compose.yml`,
`infra/Caddyfile`, `infra/edge/` (Phase 6), `frontend/src/lib/site.ts`, `frontend/src/app/routes.tsx`.
