# Frontend

React 19 + TypeScript 5.9 (strict) + Vite + Tailwind v4 + shadcn/ui (Radix) + TanStack Router/Query/Table v8 + i18next.
Binding conventions are in `../docs/ARCHITECTURE.md` section 5. This file covers how they are wired here.

## Commands

| Command             | Does                                                                                |
| ------------------- | ----------------------------------------------------------------------------------- |
| `pnpm install`      | Install dependencies (lockfile committed, `--frozen-lockfile` in CI)                |
| `pnpm dev`          | Vite on `127.0.0.1:$FRONTEND_PORT` (default 5173, strict), proxies to Django        |
| `pnpm build`        | `tsc -b` then production build to `dist/`                                           |
| `pnpm lint`         | ESLint (typescript-eslint strict, react-hooks, i18next, direction/color guards)     |
| `pnpm typecheck`    | `tsc -b --noEmit`                                                                   |
| `pnpm test`         | Vitest (jsdom): tokens contrast, i18n parity, components, API client                |
| `pnpm gen:api`      | `openapi.json` (written by `manage.py export_openapi`) to `src/lib/api/schema.d.ts` |
| `pnpm format:check` | Prettier (with the Tailwind class sorter)                                           |

Dev proxy: `/api`, `/admin` and `/static` go to `http://127.0.0.1:$BACKEND_PORT` (default 8000). Matching is per path
segment (`^/admin(/|$)`), so SPA routes such as `/administration` stay in the SPA. `changeOrigin` is off on purpose so
Django sees the browser's host: CSRF origin checks pass and the `sessionid`/`csrftoken` cookies are first-party.

## Layout

```
src/app/          router (code-based), route tree, guards, nav registry, providers, layouts, 404/error pages
src/design/       tokens.css (the only raw colors), index.css (Tailwind @theme mapping), fonts, contrast helpers
src/i18n/         i18next setup, typed resources, locales/{ar,en}/<namespace>.json
src/lib/api/      openapi-fetch client (CSRF, error normalization), generated schema.d.ts, contract types
src/lib/auth/     useMe/login/logout/change-password/preferences hooks, permission helper
src/components/   shared components (AppShell, DataTable, cards, dialogs, MoneyText, ...)
src/components/ui shadcn primitives adapted to semantic tokens and logical (RTL-safe) utilities
src/features/<m>/ routes.tsx, nav.ts, pages/ per module
src/portal/       patient portal (mobile-first layout under /portal)
```

## Adding to a feature module

All modules are already registered in `src/app/routes.ts` and `src/app/nav.ts`. Feature work edits only its folder:

- `features/<m>/routes.tsx` exports `routes(parent)`; add child routes there.
- `features/<m>/nav.ts` lists nav entries (`to` is type-checked against the router, `permission` is any-of).
- Strings go in `i18n/locales/{ar,en}/<m>.json` (same keys in both; `pnpm test` enforces parity).
- Data hooks go in `features/<m>/api.ts` using `api` + `unwrap` from `@/lib/api/client`.

The administration module lives at **`/administration`**, not `/admin`: `/admin/*` is the Django admin and is sent
to the backend by the dev proxy (and should be by the production reverse proxy), so SPA deep links there would break.

## Design tokens and themes

- `src/design/tokens.css` defines `light`, `dark`, `warm` under `[data-theme=...]`. Brand values for `--primary`,
  `--bg`, `--surface`, `--fg` are the ones in ARCHITECTURE 5.1; `src/design/contrast.test.ts` checks every text pair
  for WCAG AA (4.5:1) and input borders/focus ring for 3:1.
- Tailwind's default palette is removed (`--color-*: initial`), so only semantic utilities exist: `bg-surface`,
  `text-fg`, `text-muted`, `border-border`, `bg-primary text-primary-fg`, `text-primary-strong` (links),
  `bg-danger-bg text-danger-fg`, `bg-state-paid-bg`, `rounded-card`, `rounded-control`, `shadow-card`, ...
- In the light theme `--primary` (#0D9488) only reaches AA with dark text, so `--primary-fg` is a near-black teal.
- ESLint rejects physical direction classes (`ml-`, `pr-`, `left-`, `text-left`...), palette classes and hex/rgb
  colors in code, and literal user-visible strings in `src/{app,components,features,portal}`.
- `public/boot.js` applies the cached theme/language before first paint. Logged in, the server profile
  (`MeOut.theme/language`) wins and changes are saved with `PATCH /api/auth/me/preferences`.

## Formatting

`MoneyText` formats API decimal strings with `Intl.NumberFormat` without converting to float (Latin digits by
default; `setArabicDigitStyle("arab")` switches Arabic UI to Arabic-Indic digits). `DateText` uses the center time zone
`Africa/Khartoum`. Money columns sort with `compareDecimal` (exact string comparison).

## Style guide

`/design` (any logged-in user, also in quick search and the user menu) shows every shared component in every state.
Section containers carry `data-testid="ds-<section>"` for screenshots.
