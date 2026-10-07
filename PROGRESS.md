# Progress

Source of truth for build status. Update at the end of every task. Phases from `docs/PROMPT.md`.

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation | done (merged PR #1); Docker run pending in CI | `make check` and `make e2e` green locally; Docker exit gate (`docker compose up` shows a working login) not run: no Docker on the build machine, first run is the CI `docker` job |
| 1. Domain core + schema | done on `feat/1-domain-core`; merge to main pending | backend 1290 tests (396 domain), all passing; ADR 0006; follow-ups below |
| 2. Patients and visits | next (wave a) | |
| 3. Doctor and orders | next (wave a) | |
| 4. Billing, payments, shifts | next (wave a) | |
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

## Phase 1 checklist

- [x] `backend/domain/`: service-line state machine, pricing versions, coverage splits, invoice and
      credit-note positions, allocation and patient credit, shifts, payment verification, ledger
      postings (11 accounts incl. `CASH_SAFE`), claims, stock (units, FEFO, moves), lab ranges and
      result versions; Hypothesis property tests for the seven invariants
- [x] Full schema for every app with migrations, pghistory audit and database guards (`line_guard`,
      `dispense_line_eligible`, `claim_line_guard`, `version_guard`, frozen/append-only triggers,
      `shift_must_be_open`, deferred journal balance, `truncate_guard` on 22 tables)
- [x] Services: orders, billing, payments (shifts, handovers, refunds, frozen shift report), ledger,
      claims, pharmacy, lab, catalog, patients, visits, clinical; one router per module
- [x] Adversarial review: 54 reported issues, 49 confirmed and fixed with regression tests
- [x] ADR 0006 (Phase 1 money and stock rules); ARCHITECTURE 4.4-4.9 updated to the implementation
- [ ] Merged to main

## Follow-ups (from ADR 0006 "Differences found")

- [x] Infra: the app and maintenance run as `hospital_app` (DML only), migrations as
  `hospital_owner` through the one-off `migrate` service (`infra/db/`, `infra/db-roles.sh` for
  existing installs). Proven on local PostgreSQL 16; the compose stack, the db image's first-start
  role script and the new CI steps are first run by the CI `docker` job (no Docker here).
- [x] Frontend: every backend error code has ar and en text in `errors.json` (259 codes);
  `translateError` passes `details` so the 23 messages with placeholders show their values.
- Errors: database trigger codes (`CREDIT_NOTE_FROZEN`, `APPEND_ONLY`, `LINE_TERMINAL`, ...) are
  not mapped to API error codes and reach the user as `INTERNAL_ERROR`.
- Terminology: `الدفعة` means both a stock batch and a payment; settle on `التشغيلة` for batches
  in the pharmacy screens.
- Errors: amounts in error placeholders are raw backend strings (`15000.00`); format them with
  the money formatter when the billing screens land.
- Schema: drop or forbid `RefundMethod.bank_transfer` and refunds without a credit note
  (`payments_refund_has_source`); services already create cash refunds from credit notes only.
- Pharmacy: a `Policy` setting for `min_days_left` (domain only today); consider a DB backstop
  against dispensing from an expired batch.
- Cash: a safe count / opening balance for `CASH_SAFE` (relative balance today).
- Segregation of duties for confirming one's own transfer and approving one's own credit note
  (enforced today only for refunds and shift reviews).
- Admin: show `Policy.default_pay_first` read-only.

## Next: wave a (Phases 2-4)

Run `workflow-drafts/wave.js` with `{wave: 'a', base: 'main', prep: true}` after Phase 1 is merged:
patients and visits (FEATURES 1, 2, Excel import), doctor and orders (3, 4), billing, payments and
shifts (5, 6, 7, printing). Exit gates per `docs/PROMPT.md`: Playwright flows at three viewports,
including the full money cycle with a shift variance and a transfer rejected after close.

## Log
- 2026-10-06: repo initialized; docs moved to docs/; ARCHITECTURE.md, CLAUDE.md, ship-feature skill, ADR 0001 written.
- 2026-10-06: Phase 0 built by backend, frontend and infra agents, then integrated: e2e harness and `make e2e`,
  ADRs 0002-0004, nav permission contract test, phone tab bar short labels, patient name truncation in mixed
  scripts. Results: `make check` green (backend 370 tests, frontend 335 tests, lint, typecheck, API drift);
  `make e2e` see the latest run in this log entry's PR.
- 2026-10-07: Phase 0 review fixes (design, backend, infra lenses). Backend: one credential check for
  API, Django admin and `authenticate()` (lockout, per-address throttle 429, unknown usernames lock
  like real ones, audit via login/logout signals, admin refuses pending password changes, audited
  unlock action), change-password counts toward lockout, strict `money()` parsing, password
  validators see full names and local words, server-side request ids, JSON 404/CSRF/DoesNotExist/
  ValidationError/IntegrityError mapping, `next_number` requires a transaction, `seed_e2e` guarded
  by DB name with a separate break-glass superuser, nullable language/theme ("never chose"),
  `manage.py maintenance` (sessions, throttles). Frontend: solid focus outlines, visible menu
  highlight, full-strength control borders, 44px phone targets, 16px phone inputs, accessible
  DataTable row opening (table and cards) with container-width switching, wrapping patient names,
  tablet rail toggle, adaptive tab bar, per-page titles, bidi formatter, Arabic plural/labels fixes.
  Infra: flock locks, backup catch-up, media readable by the backup user, partial (not failed)
  backups on media errors, atomic restore swap, crash-safe `update.sh`, non-root Caddy with health
  check, `BIND_IP`, migrations check in `make check` and CI.
- 2026-10-07: Phase 0 review found 50 issues, all fixed (ADR 0005). make check green (backend 436, frontend 394 tests); make e2e 482 passed. Added TEST_DB_NAME override (must start with test_) for parallel agents. Next: Phase 1 via workflow-drafts/phase1.js on branch feat/1-domain-core.
- 2026-10-07: Phase 1 documented (ADR 0006: 16 money and stock decisions checked against the code,
  8 differences recorded as follow-ups; ARCHITECTURE 4.4-4.9 rewritten to match). Backend
  `uv run pytest -q`: 1290 passed (396 domain, 749 apps, 115 api, 30 config). Next: merge
  `feat/1-domain-core`, then wave a (Phases 2-4).
- 2026-10-07: Phase 1 integration check. Error texts for all 259 backend codes (ar, en);
  `translateError` now fills placeholders from `details`. Database role split in `infra/db/`
  (app and maintenance as `hospital_app`, migrations as `hospital_owner`). `make check` green:
  backend 1290 passed, frontend 399 passed, api-check no drift (shellcheck not installed here).
  `make e2e` 482 passed. `make infra-test` 48 checks passed. Docker steps still first run in CI.
