# 0002: The SPA administration module lives at /administration

Date: 2026-10-06. Status: accepted.

## Context
FEATURES section 13 and the module list call the administration area "admin", and the first frontend
draft routed it at `/admin`. The Django admin is also mounted at `/admin/` (break-glass tooling for the
superuser), and the command contract requires the Vite dev proxy to send `/admin` to Django. Caddy does
the same in production. With both on `/admin`, a deep link or a reload on an SPA admin page would be
answered by Django, never by the SPA.

## Decision
- The SPA administration module is mounted at `/administration` (`/administration/users`,
  `/administration/roles`, `/administration/catalog`, `/administration/price-lists`,
  `/administration/payers`, `/administration/settings`, `/administration/imports`,
  `/administration/system`). Feature folder and nav id stay `admin`.
- Only whole path segments go to Django: `^/admin(/|$)`, `^/api(/|$)`, `^/static/`. Implemented in
  `frontend/vite.config.ts` (dev) and `infra/Caddyfile` (`path /api /api/* /admin /admin/* /static/*`,
  where `/admin/*` does not match `/administration`).
- `e2e/routes.ts` registers the `/administration/*` routes, and the responsive matrix proves each one
  renders the SPA at every viewport.

## Consequences
- Links in docs and runbooks to the SPA admin use `/administration`. `/admin/` always means the Django
  admin.
- A new top-level SPA route must not start with a Django segment (`/api`, `/admin`, `/static`).
