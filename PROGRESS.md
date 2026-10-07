# Progress

Source of truth for build status. Update at the end of every task. Phases from `docs/PROMPT.md`.

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation | integrated, exit gate pending | `make check` and `make e2e` green locally; Docker exit gate (`docker compose up` shows a working login) not run: no Docker on the build machine, first run is the CI `docker` job |
| 1. Domain core + schema | not started | |
| 2. Patients and visits | not started | |
| 3. Doctor and orders | not started | |
| 4. Billing, payments, shifts | not started | |
| 5. Pharmacy, lab, procedures | not started | |
| 6. Claims, reports, admin, ops | not started | |
| 7. Patient portal | not started | |
| 8. Hardening and handover | not started | |

## Phase 0 checklist

- [x] Repo layout per ARCHITECTURE 1; Makefile targets per ARCHITECTURE 2; per-worktree DB names and ports (`scripts/`)
- [x] Backend: settings from env, `domain/` (money, splits, lockout, numbering, permissions) with Hypothesis tests
- [x] Backend: custom User, 11 roles, permission registry + override matrix, CenterProfile/Policy, numbering, audit (pghistory)
- [x] Auth API (csrf, login with lockout, logout, me, preferences, change-password) and `/api/ops/health` (ADR 0004)
- [x] `export_openapi` (committed `frontend/openapi.json`), `seed_e2e`
- [x] Frontend: tokens and three themes (AA contrast test), bundled fonts, ar/en + RTL, typed API client from OpenAPI
- [x] Frontend: shared components (ARCHITECTURE 5.4), app shell, login, forced password change, dashboard, `/design`,
      module placeholders, portal, 404; SPA administration at `/administration` (ADR 0002)
- [x] E2E harness: `make e2e` resets `e2e_hospital_<hash>`, seeds, starts both servers, runs auth, offline and the
      responsive matrix (every route x 3 viewports x 3 themes x 2 languages) with screenshots
- [x] Infra: Dockerfiles, compose, Caddyfile, backup/restore, update with rollback, CI workflow, runbooks, device agent
- [ ] Docker images built and compose stack run (CI `docker` job; not possible on the build machine)
- [ ] shellcheck run (CI `infra` job; not installed on the build machine)

## Log
- 2026-10-06: repo initialized; docs moved to docs/; ARCHITECTURE.md, CLAUDE.md, ship-feature skill, ADR 0001 written.
- 2026-10-06: Phase 0 built by backend, frontend and infra agents, then integrated: e2e harness and `make e2e`,
  ADRs 0002-0004, nav permission contract test, phone tab bar short labels, patient name truncation in mixed
  scripts. Results: `make check` green (backend 370 tests, frontend 335 tests, lint, typecheck, API drift);
  `make e2e` see the latest run in this log entry's PR.
