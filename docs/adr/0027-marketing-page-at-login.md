# 0027: A marketing page at /login, switched on per deployment; the staff sign-in is /sign-in

Date: 2026-10-27. Status: accepted. Related: 0005 (one door, abuse control), 0023 (center page), 0026 (session expiry).

## Context
The owner runs a public deployment (`https://healtfull.stingdev.pro`) that hospital and clinic
buyers in Sudan open first. Its `/login` should sell the system, with a clear way to the real
sign-in. Every other install is a private LAN deployment of one center, where `/login` must stay
the plain staff sign-in: a center's staff have no use for a sales page, and nothing about it
should change for them.

## Decisions
- **Two addresses for the staff sign-in.** `/sign-in` is the canonical staff sign-in (the same
  `LoginPage`: same form, same accessible names, same lockout and per-address abuse control: the
  API behind it is untouched). `/login` is its alias.
- **A deployment setting, default off.** `MARKETING_SITE=1` (env, `backend/config/settings.py`)
  turns `/login` into the marketing page. Unset or `0`: `/login` behaves exactly as before.
  Optional `MARKETING_CONTACT_EMAIL` and `MARKETING_CONTACT_WHATSAPP` (international digits) give
  the page plain contact links; a value that is not an address or digits is dropped, and with
  neither set the page shows only "a demo is available on request". No phone number, price or
  account is ever printed.
- **Read at run time, no rebuild.** The setting is exposed by `GET /api/ops/site` (public, no
  session, like `/api/ops/health`): `{marketing, contact_email, contact_whatsapp}`, the contact
  values only while marketing is on. The SPA reads it once before its first render
  (`frontend/src/lib/site.ts`, 3 s timeout) so every redirect already knows the answer. A server
  that does not answer leaves it off: a plain sign-in always works. One built image serves every
  deployment; the env change needs the app container recreated (`infra/compose.sh up -d`), not
  an image rebuild.
- **Every sign-in redirect follows the setting.** `signInPath()` returns `/sign-in` when
  marketing is on and `/login` when off: the route guards, the 401 handling, the re-authentication
  dialog, sign-out, the kiosk sign-out and the portal's "staff sign-in" link. So with the setting
  off the suite's `/login` expectations hold; with it on, signed-out visitors land on `/sign-in`
  with `?redirect=`. `safeRedirectTarget` refuses both as post-sign-in targets.
- **One action, repeated.** The page's single call to action is "Sign in to the system" (to
  `/sign-in`): in the sticky header, after the hero, the cycle, the rules, the roles and the
  network sections, in the closing section, and in a sticky bar on phones. Secondary actions are
  text links. The page is code-split: a private install never downloads it.
- **No invented evidence.** The page states the seven invariants of CLAUDE.md as plain promises,
  the facts the runbooks prove (runs on the center's network with no internet, nightly backup and
  monthly restore test, daily integrity check, UPS shutdown, Arabic and English) and the
  screens, with screenshots of the demo system (synthetic data). It claims no customers, counts,
  ratings, regulator, price, offer or test numbers. Copy limits (headline, subhead, sentence
  length, long words, 745 words, no digits or evidence words) are unit tests over the strings.
- **Search.** `public/robots.txt` allows only `/login`; Open Graph tags are static in
  `index.html` with no image (an image tag needs an absolute URL, which a build does not know).

## Consequences
- The e2e suite stays on the off default. One spec (`e2e/tests/marketing/marketing.spec.ts`, tag
  `@marketing`) turns the page on by answering `/api/ops/site` in the browser and runs the matrix
  (3 viewports x 3 themes x 2 languages), the call-to-action count and target, the real sign-in
  from the button and sign-out back to `/sign-in`, the contact and weight checks; one test reads
  the real endpoint and asserts off. The backend switch is proved by pytest.
- The first load of the page includes the whole app bundle (about 700 KB compressed), because the
  SPA is one bundle; the sign-in a click later costs nothing extra. Splitting routes would cut it
  (follow-up).
- `/sign-in` is in the e2e route registry; `/login` stays registered for the off default.

## Code
`apps/ops/{api,services,schemas}.py`, `config/settings.py`; frontend `src/lib/site.ts`,
`src/app/guards.ts`, `src/features/auth/routes.tsx`, `src/features/marketing/`,
`src/i18n/locales/{ar,en}/marketing.json`, `src/assets/marketing/`; `.env.example`.

## Addendum (2026-10-28): the page also opens at the site root
With marketing on, `/` renders the same page (same component, same call to action) when the
visitor has **no staff session**. The `_app` route's guard reads the session first (the cached
`/api/auth/me` answer), then chooses, so a signed-in user gets the dashboard at `/` with no flash
of the page. Only the exact path `/` is affected: every protected route still redirects a
signed-out visitor to `/sign-in?redirect=...`, `/login` keeps the page, `/portal` stays the center
page and the kiosk routes are unchanged. With marketing off nothing changes at `/` (signed out
goes to `/login`). `robots.txt` allows `/` and `/login`. Code: `src/app/routes.tsx` (`AppEntry`,
route context `marketingRoot`), `src/features/marketing/LazyMarketingPage.tsx`.
