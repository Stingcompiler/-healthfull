# Changelog

All notable changes. Format: Keep a Changelog. Versioning: SemVer.

## [Unreleased]
### Added
- Project decision documents, architecture conventions, agent rules, ship-feature skill.
- Phase 0 backend foundation: Django 5.2 + django-ninja, env-driven settings, pure `domain/` package
  (money, splits, lockout, numbering, permissions; Hypothesis-tested), custom User with 11 roles,
  permission registry and override matrix, CenterProfile and Policy singletons, gap-free document
  numbering, reason codes, departments, rooms, doctor profiles, notifications, append-only auth events,
  pghistory audit on config models.
- Auth API: `/api/auth/{csrf,login,logout,me,me/preferences,change-password}` with session + CSRF,
  5-failure / 15-minute lockout (ADR 0004), forced password change; `/api/ops/health`.
- `manage.py export_openapi` and `seed_e2e`; OpenAPI committed at `frontend/openapi.json`.
- Phase 0 frontend foundation: React 19, Vite, TypeScript strict, Tailwind v4 with semantic tokens for
  three themes (light, dark, warm), bundled fonts, Arabic/English with RTL, typed API client generated
  from OpenAPI, shared component library, app shell, login, forced password change, dashboard,
  `/design` style guide, module placeholders, portal and 404 pages.
- Infrastructure: Makefile entry points, per-worktree ports and DB names (`scripts/`), Dockerfiles,
  compose, Caddyfile, backup/restore and update scripts, CI workflow, runbooks, local device agent.
- E2E harness (`e2e/`, `make e2e`): per-worktree e2e database, Playwright starting both servers, auth,
  offline (no non-local requests) and responsive specs (every route x 3 viewports x 3 themes x 2
  languages, screenshots to `artifacts/screens/`).
- ADRs 0002 (SPA administration at `/administration`), 0003 (light-theme primary foreground),
  0004 (sign-in, lockout and session semantics).
