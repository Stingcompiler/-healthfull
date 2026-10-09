# Progress

Source of truth for build status. Update at the end of every task. Phases from `docs/PROMPT.md`.

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation | done (merged PR #1); Docker run pending in CI | `make check` and `make e2e` green locally; Docker exit gate (`docker compose up` shows a working login) not run: no Docker on the build machine, first run is the CI `docker` job |
| 1. Domain core + schema | done on `feat/1-domain-core`; merge to main pending | backend 1290 tests (396 domain), all passing; ADR 0006; follow-ups below |
| 2. Patients and visits | done on `wave/a` (merged from `feat/a-patients`); merge to main pending | FEATURES 0.9, 1.1-1.6, 1.8, 2.1-2.7 |
| 3. Doctor and orders | done on `wave/a` (merged from `feat/a-clinic`); merge to main pending | FEATURES 3.1-3.9, 4.1, 4.2 (4.3, 4.5 as services); follow-ups below |
| 4. Billing, payments, shifts | done on `wave/a` (merged from `feat/a-cashier`); merge to main pending | FEATURES 0.10 (invoice, receipt, shift report), 4.4, 5.3, 5.4, 5.6, 5.8-5.11, 6.1-6.9, 7.1-7.6; follow-ups below |
| 5. Pharmacy, lab, procedures | pharmacy done on `feat/b-pharmacy` (wave b); lab and procedures not started | FEATURES 5.12, 8.1-8.10; follow-ups below |
| 6. Claims, reports, admin, ops | admin part done on `wave/a` (merged from `feat/a-admin`) | FEATURES 0.1-0.3, 5.2, 5.5, 11.1, 13.1-13.3; claims, reports and ops not started |
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
- [x] Segregation of duties for confirming one's own transfer and approving one's own credit
  note (ADR 0008, `SELF_CONFIRMATION_NOT_ALLOWED`, `CREDIT_NOTE_SELF_APPROVAL`).
- Admin: show `Policy.default_pay_first` read-only.

## Follow-ups (clinic, wave a review)

- Print: referral letters and prescriptions have no print view yet. The A4/80 mm templates of
  FEATURES 0.10 landed with the cashier module but live in `features/cashier`
  (`components/PrintFrame.tsx`, `components/print.css`, `DocHeader` in `pages/ReceiptPage.tsx`),
  and the document header reads the center profile from billing endpoints a doctor cannot
  call. Wiring the clinic needs: move the frame, stylesheet and header to `src/components/print/`,
  a center header the doctor may read (core), two print routes (`/clinic/visits/$visitId/
  referrals/$id/print`, `.../prescription/print`) with ar/en strings, responsive-matrix entries in
  `e2e/module-routes/clinic.ts` and a print e2e. Not done in the wave a integration.
- Results tab screenshots show the empty state only: approved results need the lab module's
  endpoints (FEATURES 4.x lab); add a populated capture to `e2e/tests/clinic/states.spec.ts`
  then.
- Nurses: vitals (FEATURES 3.4) are entered from the doctor's workspace; a nurse has no list
  of visits to reach it until the nursing screens of FEATURES 10.3.
- Work lists and exception reports (FEATURES 4.3, 4.5) exist as tested services
  (`orders.services.worklist_lines`, `report_*`); their endpoints and screens come with the
  lab, pharmacy, procedures and reports modules.
- [x] Billing access sweep for doctors (`e2e/tests/clinic/access.spec.ts`): runs against every
  billing and payments operation of the contract now that the cashier module publishes them,
  and fails (never passes empty) if the contract has none.
- Schema names (fixed on `wave/a`): django-ninja publishes one OpenAPI component per class
  name, so equal names in two apps collide. Visits now uses `VisitDepartmentOut`,
  `VisitDoctorOut`, `VisitRoomOut` and patients `PatientPayerOut`;
  `api/tests/test_main.py::test_schema_class_names_are_unique_across_apps` fails on any clash.

## Follow-ups (wave a integration)

- [x] Billing, payments and shifts (Phase 4, `feat/a-cashier`): merged in the second wave a
  integration (see the log).
- Kiosk: `/display/queue` runs in a signed-in session of a user with `visits.view_queue`; a
  display-only role needs a core role change.
- Paid-visit cancellation: reception sees the `billed` flag and a supervisor
  (`cashier_supervisor`) cancels directly; there is no in-app request for supervisor approval.
- `/administration/imports` is still the placeholder section; it can link to `/patients/import`
  when the item and price imports land.
- Admin: a role with `core.manage_departments` but no `catalog.view` sees an empty consultation
  fee picker in the doctor dialog (it reads `/api/catalog/services`).
- Allergy `resolved` needs no reason (entered-in-error does); referral cancellation has no
  supervisor exception (ADR 0007).
- shellcheck is not installed on the build machine; `lint-shell` ran `bash -n` only, CI runs
  shellcheck.

## Follow-ups (cashier, wave a)

- FEATURES 0.10: invoice, receipt (QR, 6.9) and shift report print on A4 and 80 mm; the
  prescription, lab result and claim export templates come with the clinic print views (above),
  the lab module and claims.
- FEATURES 5.12 (walk-in pharmacy sale) exists as a tested service
  (`billing.services` walk-in sale) with its permission; the screen comes with the pharmacy
  module.
- FEATURES 7.7 (multi-till, V1?): a shift may name its till when it opens; several cashiers on
  one till per shift is not built.
- Errors: amounts in error placeholders are still raw backend strings (see the Phase 1
  follow-up); the cashier screens format their own amounts with `MoneyText`.
- The Phase 1 schema follow-up on `RefundMethod.bank_transfer` is unchanged: refunds are paid in
  cash from a credit note only.

## Follow-ups (pharmacy, wave b)

- FEATURES 8.13 (Excel import of items, batches and opening stock) is not built; the
  `/administration/imports` section can link to it when it lands.
- Dispense returns (`pharmacy.services.return_dispense`) have no endpoint or screen yet.
- Stock lists show the item's generic name and strength (Latin, as printed on packs); the item
  has no Arabic generic name. The queue, dispense dialog and sale use the bilingual service name.
- A new walk-in customer gets a patient file without the duplicate check (the sale screen offers
  "existing file" search first); reception merges duplicates later (FEATURES 1.4).
- The walk-in sale screen sits under the pharmacy nav entry (pharmacy codes); a cashier, who
  also holds `billing.pharmacy_sale`, reaches it by URL only.
- An adjustment's batch picker lists batches with stock in the store; raising a batch that has
  none there (found stock of an empty batch) needs a goods receipt or a transfer.
- No dispense label or prescription print (FEATURES 0.10/0.11 with the device agent).
- The Phase 1 `min_days_left` policy follow-up is unchanged (FEFO uses expiry >= today).

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
- 2026-10-07: Wave a preparation on `wave/a` (from `feat/1-domain-core`): `seed_e2e` now seeds a
  realistic base catalog (9 departments, 4 doctors with schedules, 34 services of every kind, cash +
  3 payer price lists with effective versions, payers with percentage/copay/ceiling rules and one
  exclusion, 12 stock items with units and two batches in two stores, 6 lab tests with ranges,
  wards and 9 beds, tills, reason codes). `manage.py e2e_fixture` builds patients, visits, orders,
  invoices, payments and shifts through the services as the acting seed user;
  `e2e/helpers/api.ts` gives per-role CSRF-aware API clients and typed factories that switch to
  real endpoints through `e2e/helpers/adapters/<module>.ts` (see `e2e/README.md`); screens are
  listed per module in `e2e/module-routes/<module>.ts`. Module builders of wave a need no edits
  to these shared files (still shared: `errors.json` and the generated OpenAPI files).
  `make check` green (backend 1321 passed, frontend 399 passed, no API drift; shellcheck not
  installed here); `make e2e` 491 passed (9 new `@helpers` tests).
- 2026-10-08: Patients and visits review fixes on `feat/a-patients` (wave a). Built FEATURES 1.8
  (Excel/CSV patient import: `domain/patient_import.py`, `apps/imports/services.py`,
  `/api/imports`, screen `/patients/import`) and patient results in the global quick search
  (0.9). Finishing a consultation needs `visits.finish_consultation` (doctor, admin); visits
  and board rows carry `billed` so reception sees that a supervisor must cancel a paid visit;
  doctors read the appointment day; token slips count only paid tokens ahead; list rows show
  only a coverage valid today; merge and appointment-cancel reasons are ReasonCode rows
  (`patient_merge`, `appointment_cancel`, core migration 0009). `require_perm` now refuses a
  caller without the permission before the body is validated (403, never 422), with per-module
  route contract tests. Waiting-room screen is the kiosk route `/display/queue` (no shell, no
  exit, offline screen). Every patients/visits query shows a failure with a retry. UI review
  fixes (emergency badge, no-show confirmation, sex not preselected, 80 mm print page, compact
  free slots, focus management, Arabic copy). E2E API clients start with an empty cookie jar.
  Results: `make check` green (backend 1430 passed, frontend 405 passed, mypy and eslint clean,
  no API drift; shellcheck not installed here); `make e2e` with `@patients` plus the responsive
  matrix of patients, patient-new, patient-import, patient-file, queue, queue-display and
  appointments: 151 passed. Full `make e2e`: 586 passed, 1 failed (768px queue-display light en:
  the browser session closed while the feed loaded; the 18 queue-display cases then passed on a
  rerun).
  Integration notes: core migration `0009_reason_categories_merge_appointment` and
  `feat/a-admin`'s `0009_authevent_password_reset` need a merge migration; the admin reason-code
  screens need labels for the two new categories; `/administration/imports` can link to
  `/patients/import`; a display-only role for the kiosk needs a core role change.
- 2026-10-08: Clinic (doctor and orders) on `feat/a-clinic`, merged with `wave/a` (admin and
  patients). Clinic schemas renamed where they shared an OpenAPI component name with patients
  and visits (`PatientAllergyOut`, `ClinicPatientOut`, `ClinicUserRefOut`, `ClinicPayerRefOut`,
  `WithdrawReasonOut`); the doctor billing sweep switches on with the cashier module; clinic
  dialog screenshots are viewport captures. Results: backend 1578 passed, frontend 421 passed,
  mypy clean, ruff and prettier clean, no API drift; `make e2e E2E_GREP=@clinic` plus the
  clinic and clinic-visit responsive matrix: 50 passed, 1 skipped (billing sweep, no money
  operations yet). `make check` stops at the frontend lint/typecheck of the admin screens
  because of the wave a `DoctorOut` collision (see clinic follow-ups).
- 2026-10-09: Clinic second review fixed on `feat/a-clinic`: withdrawal needs `clinical.view` and
  refuses started lines (`LINE_IN_PROGRESS`); clinic completion needs
  `visits.finish_consultation`; referral cancellation, diagnosis removal and allergy/condition
  entered-in-error carry a reason (migration `clinical.0006`); favorites keep route, dose
  quantity and as-needed; early allergy warnings (`/api/clinical/patients/{id}/allergy-alerts`);
  unsaved-changes guard on the workspace; UI, a11y and Arabic wording fixes (ADR 0007
  addendum). Results: backend 1588 passed, frontend 424 passed, mypy and ruff clean, API
  contract in sync, no missing migrations; `make e2e E2E_GREP=@clinic` 14 passed, 1 skipped
  (billing sweep); clinic responsive matrix 36 passed. Frontend lint/typecheck still stop at
  the admin screens' wave a `DoctorOut` collision (unchanged, see clinic follow-ups).
- 2026-10-09: Wave a integration on `wave/a`: merged `feat/a-patients` (FEATURES 0.9, 1.1-1.6,
  1.8, 2.1-2.7), `feat/a-admin` (0.1-0.3, 5.2, 5.5, 11.1, 13.1-13.3; merged twice, the second
  time for its review fixes) and `feat/a-clinic` (3.1-3.9, 4.1, 4.2; this round's review covered
  3.2, 3.5-3.7, 3.9, 4.2). Core merge migration `0010_merge_wave_a_admin_patients`; generated API
  files regenerated with `make api` at each merge. Integration fixes: OpenAPI component names
  made unique across apps (visits `Visit*Out`, patients `PatientPayerOut`; guard test in
  `api/tests/test_main.py`), which unblocks the admin screens' lint and typecheck; the
  `patient_merge` and `appointment_cancel` reason categories on the reason-code API and admin
  screen (ar and en labels); the helpers e2e spec expects `ALLERGY_CONFLICT`. Results:
  `make check` green (backend 1597 passed, frontend 427 passed, ruff, mypy, eslint, prettier and
  tsc clean, no missing migrations, API contract in sync; shellcheck not installed here). Full
  `make e2e`: 725 passed, 2 failed, 1 skipped (37.5 min). The failures were the helpers spec
  (fixed above) and `@admin users` create-and-sign-in (`ECONNRESET` from the dev server on
  `/api/auth/me`). The rerun of `@helpers|@admin users` passed 11 of 11. The skip is the doctor
  billing sweep, which waits for the cashier module. `feat/a-cashier` (Phase 4) is not part of
  this merge.
- 2026-10-09: Wave a complete on `wave/a`: merged `feat/a-cashier` (Phase 4; FEATURES 0.10 for
  invoice, receipt and shift report, 4.4, 5.3, 5.4, 5.6, 5.8-5.11, 6.1-6.9, 7.1-7.6; its review
  found 22 issues, all fixed on the branch, ADR 0008). Conflicts: `orders/api.py` (clinic order
  endpoints kept, perform-first router mounted at `/api/orders/perform-first`), `ui/tabs.tsx`
  (cashier's 44px phone tabs), `CHANGELOG.md` (both entries); generated API files regenerated
  with `make api`. Integration fixes: billing `PatientSummaryOut` renamed
  `BillingPatientSummaryOut` (collided with clinical's); the cashier's ADR 0007 (desk approvals)
  renumbered 0009; the doctor billing sweep runs (no `fixme`) and fails on an empty contract;
  an empty credit note shows its "at least one unit" message (`qty.root`); the helpers spec
  accepts module fixture payers. No migration clashes (cashier added none). Clinic print views
  not wired to the cashier print frame (see clinic follow-ups). Results: `make check` green
  (backend 1678 passed, frontend 440 passed, ruff, mypy, eslint, prettier and tsc clean, no
  missing migrations, API contract in sync; shellcheck not installed here). Full `make e2e`:
  977 passed, 0 failed, 0 skipped (43.8 min). The first full run had 975 passed, 2 failed
  (the credit note message and the helpers payer set, both fixed above, then 7 of 7 passed in a
  rerun of `@cashier refund|@helpers factories`).
- 2026-10-09: Pharmacy (wave b) on `feat/b-pharmacy` from `wave/b`: FEATURES 5.12, 8.1-8.10.
  `/api/pharmacy` (46 operations: queries.py reads, desk.py commands, one `require_perm` each),
  services extended (item edits and barcodes, suppliers, stock card, adjustment and transfer
  requests refuse more than on hand); pharmacy screens under `src/features/pharmacy` (dispense
  queue and dialog, items and item page, receipts, adjustments, counts and count sheet,
  transfers, expiry, low stock, walk-in sale); batches are "التشغيلة" (also the batch-override
  reason, core 0007 copy plus pharmacy migration 0004). Self-review fixed the item search
  multiplying on-hand by pack units. Results: backend 1708 passed, ruff, mypy, eslint, prettier
  and tsc clean, no missing migrations, API contract in sync; frontend 447 passed (run with
  `--testTimeout=30000`: under a machine load of 30-45 the default 5 s timeout failed 1-6 tests
  of the untouched shared DataTable/AppShell/KpiCard/radio-group suites, a different set each
  run). `make e2e E2E_GREP=@pharmacy`: 7 passed; responsive matrix of the 12 pharmacy routes
  plus the route registry: 217 passed.
