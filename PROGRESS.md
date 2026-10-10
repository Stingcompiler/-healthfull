# Progress

Source of truth for build status. Update at the end of every task. Phases from `docs/PROMPT.md`.

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation | done (merged PR #1); Docker run pending in CI | `make check` and `make e2e` green locally; Docker exit gate (`docker compose up` shows a working login) not run: no Docker on the build machine, first run is the CI `docker` job |
| 1. Domain core + schema | done on `feat/1-domain-core`; merge to main pending | backend 1290 tests (396 domain), all passing; ADR 0006; follow-ups below |
| 2. Patients and visits | done on `wave/a` (merged from `feat/a-patients`); merge to main pending | FEATURES 0.9, 1.1-1.6, 1.8, 2.1-2.7 |
| 3. Doctor and orders | done on `wave/a` (merged from `feat/a-clinic`); merge to main pending | FEATURES 3.1-3.9, 4.1, 4.2 (4.3, 4.5 as services); follow-ups below |
| 4. Billing, payments, shifts | done on `wave/a` (merged from `feat/a-cashier`); merge to main pending | FEATURES 0.10 (invoice, receipt, shift report), 4.4, 5.3, 5.4, 5.6, 5.8-5.11, 6.1-6.9, 7.1-7.6; follow-ups below |
| 5. Pharmacy, lab, procedures | done on `wave/b` (merged from `feat/b-pharmacy`, `feat/b-lab`, `feat/b-nursing`); merge to main pending | FEATURES 5.12, 8.1-8.10 (pharmacy); 9.1-9.8 (lab, ADR 0010); 3.4 for nurses, 10.1-10.3, 10.5 (nursing and procedures, ADR 0011); follow-ups below |
| 6. Claims, reports, admin, ops | done on `wave/c`: admin on `wave/a` (from `feat/a-admin`); claims on `wave/b` (from `feat/b-claims`); reports and ops on `wave/c` (from `feat/c-reports`, `feat/c-ops`) | FEATURES 0.1-0.3, 5.2, 5.5, 11.1, 13.1-13.3 (admin); 11.2-11.7 (claims, ADR 0012); 4.5, 12.1-12.11 (reports and dashboard, ADR 0013); 1.8 wizard, 8.13, 0.13, 13.8-13.10, audit viewer (ops, ADR 0014); follow-ups below |
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
- [x] Terminology: `الدفعة` means both a stock batch and a payment; settle on `التشغيلة` for batches
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
- [x] Nurses: vitals (FEATURES 3.4) are entered from the doctor's workspace; a nurse has no list
  of visits to reach it until the nursing screens of FEATURES 10.3. Done on `feat/b-nursing`:
  `/nursing/visits` leads to the nursing chart.
- [x] Work lists and exception reports (FEATURES 4.3, 4.5) exist as tested services
  (`orders.services.worklist_lines`, `report_*`). The lab, pharmacy and procedure work lists
  have their endpoints and screens since wave b; the exception reports are reports screens
  since wave c (`/reports/requested-not-invoiced` and the two others).
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
- [x] `/administration/imports` is the import wizard since wave c (ops follow-ups).
- Admin: a role with `core.manage_departments` but no `catalog.view` sees an empty consultation
  fee picker in the doctor dialog (it reads `/api/catalog/services`).
- Allergy `resolved` needs no reason (entered-in-error does); referral cancellation has no
  supervisor exception (ADR 0007).
- shellcheck is not installed on the build machine; `lint-shell` ran `bash -n` only, CI runs
  shellcheck.

## Follow-ups (cashier, wave a)

- FEATURES 0.10: invoice, receipt (QR, 6.9) and shift report print on A4 and 80 mm; the
  prescription, lab result and claim export templates come with the clinic print views (above),
  the lab module and claims. The lab result (A4) and tube label prints landed with the lab
  module (wave b); prescription and claim export prints are still open.
- [x] FEATURES 5.12 (walk-in pharmacy sale) exists as a tested service
  (`billing.services` walk-in sale) with its permission; the screen comes with the pharmacy
  module. Done on `feat/b-pharmacy` (`/pharmacy/sale`).
- FEATURES 7.7 (multi-till, V1?): a shift may name its till when it opens; several cashiers on
  one till per shift is not built.
- Errors: amounts in error placeholders are still raw backend strings (see the Phase 1
  follow-up); the cashier screens format their own amounts with `MoneyText`.
- The Phase 1 schema follow-up on `RefundMethod.bank_transfer` is unchanged: refunds are paid in
  cash from a credit note only.

## Follow-ups (pharmacy, wave b)

- [x] FEATURES 8.13 (Excel import of items, batches and opening stock) built in wave c (ops,
  ADR 0014).
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

## Follow-ups (nursing, wave b)

- [x] Bed nights reach the cashier when a nurse posts them on the bed board, at discharge, or when
  `manage.py charge_bed_nights --as <user>` runs; since wave c the compose `maintenance` loop
  runs it hourly as `BED_CHARGE_USER` (ops follow-ups).
- No "admission in error" action: `AdmissionStatus.CANCELLED` exists but has no reason, approver
  and time columns (invariant 4). Today the nurse discharges and the cashier credits the night.
- The doctor's workspace shows the vitals a nurse records, but not the nursing notes (they are on
  the nursing chart, which doctors can open).
- Consumables used per procedure (FEATURES 10.4, P2) and the medication administration record
  (10.6, Later) are not built.

## Follow-ups (lab, wave b)

- The clinic's results tab can now show approved results; its screenshot in
  `e2e/tests/clinic/states.spec.ts` still captures the empty state (clinic follow-up above).
- Results reach the patient with the portal (Phase 7); FEATURES 9.4 "visible to the patient"
  is not wired yet.
- Lab prints (`LabPrintFrame`) import the cashier's `features/cashier/components/print.css`
  across features; moving the print frame and stylesheet to `src/components/print/` (clinic
  follow-up) should take the lab with it.
- Result PDF is the browser's print to PDF of the A4 report; tube labels print 50 x 30 mm from
  the browser, not through the device agent (FEATURES 0.11).
- A paid test that cannot be performed needs a billing approver (cashier supervisor or
  accountant) at the bench; the refund itself is approved by a second person at the cashier
  (ADR 0010, ADR 0008).
- A lab supervisor may approve a result they entered (ADR 0010); revisit if centers want a
  second-person check.
- Outsourced tests, analyzer integration and radiology (FEATURES 9.9-9.11, P2) are not built.

## Follow-ups (claims, wave b)

- FEATURES 11.5 asks for approval of rebills and write-offs: today the recording user with
  `claims.resolve_rejection` is the approver (reason and time recorded, no second person;
  ADR 0012). Add a second-person check if centers want one.
- One export layout (Excel and A4 print, Arabic or English) for every payer; a payer that wants
  its own column order or codes needs a per-payer export template (ADR 0012).
- A payer cash payment goes into the recorder's own open shift; an accountant has no till, so a
  supervisor with an open shift records it.
- Electronic claim submission (FEATURES 11.8, Later) is not built; claim export templates of
  FEATURES 0.10 are the claims print above.

## Follow-ups (wave b integration)

- ADR numbers: lab took 0010, nursing's ADR was renumbered 0011 at the merge and claims uses
  0012; the next ADR is 0013.
- E2E across midnight: specs that build "today's" data once in `beforeAll` (the clinic doctor
  states spec) fail when a full run crosses midnight, and the seed's scheduled +10% cash price
  version (starting the day after the seed) takes effect mid-run. Pin the date or build per test
  if CI runs at night.

## Follow-ups (reports, wave c)

- PDF is the browser's print of `/reports/<key>/print` (A4 landscape); server-side PDF needs
  WeasyPrint and system libraries (pango) that are not installed (ADR 0013).
- The report print view imports the cashier's `features/cashier/components/print.css` like
  the claims and lab prints do; it moves with them to `src/components/print/` (clinic
  follow-up).
- Collections are reported by the day a payment was taken at its current verification: a
  transfer confirmed or rejected later changes that earlier day's split (ADR 0013). A
  "by confirmation day" view is not built.
- Payer receivables read per payer through `claims.queries` (query count grows with payers).
- The dashboard's low-stock alert has no report to open (no low-stock report screen beyond the
  pharmacy's own list); 12.12-12.14 (P2) are not built.
- Pre-existing, outside reports: `domain/tests/test_visit_machine.py::TestVisitMachine` fails
  with a Hypothesis example (saved in this worktree's `backend/.hypothesis`): after a bank
  transfer with `allow_partial=False` and an opening float of 0.01, rejecting a still-pending
  transfer plans `uncovered` 10.14 (and in a second example a recovery row of -1205.00), which
  the model says is impossible for pending money. Needs a look in `domain/allocation.py`
  (`plan_rejection`) or the model. Being fixed on `fix/plan-rejection-pending`; on `wave/c`
  (no saved example) the test passed in `make check`.
- Detail sections stop at 2,000 rows (the screen and the workbook say so); a paged export for
  very long periods is not built.

## Follow-ups (ops, wave c)

- [x] `/administration/imports` is the import wizard (patients, items with opening stock,
  prices); `/patients/import` keeps working on the same service.
- [x] FEATURES 8.13 built (ADR 0014): opening stock is a goods receipt from the `OPENING`
  supplier per store.
- [x] Bed nights are charged by the maintenance loop as `BED_CHARGE_USER` (empty skips it).
- Manual backups need the backup service: in development and e2e a request stays pending.
- `UpdateRun` rows are not written by `infra/update.sh` yet; the update history shows its JSON
  log (`update-runs.jsonl`) and any recorded `UpdateRun` with release notes. Writing release
  notes into `UpdateRun` from the update script is open (13.10 "update trigger" stays the
  runbook's `infra/update.sh`).
- Notifications are polled every minute (no push); the bell lists the latest 15.
- Model names in the audit viewer are translated for the main records; the rest show Django's
  English verbose name. Field names are shown as database columns.
- The full export reads every row of nine tables in one request (streamed); very large
  installations may prefer a scheduled export to the backup disk.

## Follow-ups (wave c integration)

- ADR numbers: reports took 0013 and ops 0014; the next ADR is 0015.
- The payment-engine bug found by `test_visit_machine.py` (reports follow-ups) is fixed on its
  own branch, `fix/plan-rejection-pending`; merge it before `wave/c` goes to `main`.
- E2E under load: setup-heavy responsive cases (`nursing-desk` builds a paid procedure through
  several `e2e_fixture` calls; `patient-file` waits until no region of the file is still
  loading) exceed the 30 s test timeout when the machine is loaded or wakes from sleep. After
  a timeout the worker restarts and builds its data again, so failures come in runs. Building
  this data once in a global setup, or a longer timeout for these cases, would remove it.
- The full e2e now takes far longer on this machine (1657 tests); CI runs four shards.

## FEATURES 14 (data protection and operations) status

- 14.1: nightly verified `pg_dump` with media archive, optional pgBackRest WAL archiving (repo1
  local, repo2 S3 when online), monthly `restore-test.sh`; since wave c the status page
  (`/administration/system`) shows backups and restore tests from the status logs and takes
  manual backup requests. Scripts tested by `make infra-test`; the containers run first in the
  CI `docker` job.
- 14.2: database triggers on approved invoices, closed shifts and the other frozen tables
  (Phase 1, ARCHITECTURE 4.9).
- 14.3: role-based permission codes on every router; doctors hold no billing codes.
- 14.4: sign-in audit (`AuthEvent`), lockout and throttling (Phase 0, ADR 0004); the audit trail
  viewer since wave c.
- 14.5: pgBackRest repositories are always encrypted (`aes-256-cbc`, `infra/backup/`).
- 14.6: `docs/runbooks/backup-restore.md` and `install.md`; a timed replace-the-server drill
  has not been run (no Docker on the build machine).

## Next: merge waves b and c to main

Pharmacy, lab, nursing and claims are merged on `wave/b`; reports and ops on `wave/c` (built
from `wave/b`). Merge `fix/plan-rejection-pending`, then take `wave/c` to `main`. The patient
portal (Phase 7) is being built on `feat/c-portal`.

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
- 2026-10-09: Nursing (wave b) on `feat/b-nursing` from `wave/b`: FEATURES 3.4 for nurses,
  10.1-10.3 and 10.5 (ADR 0011). Backend: `/api/orders/procedures` (work list of paid or
  authorized procedures, done today, one-tap done with who, when and note), `/api/clinical/
  nursing` (inpatients and today's visits, nursing chart, notes), `/api/visits/inpatient` (bed
  board, admit on an open or new inpatient visit, transfer, discharge, bed status, nightly charge
  run) and `manage.py charge_bed_nights`; nurses hold `visits.admit`; race tests for two taps,
  two admissions and two transfers into one bed; 403 sweeps per router. Frontend: `/nursing`
  (tablet cards, five-second undo window), `/nursing/visits`, `/nursing/visits/$visitId`,
  `/nursing/beds` with admit, transfer and discharge dialogs. Results: `make check` green
  (backend 1735 passed, frontend 445 passed, ruff, mypy, eslint, prettier and tsc clean, no
  missing migrations, API contract in sync; shellcheck not installed here). `make e2e
  E2E_GREP="@nursing|@responsive.*nursing|route registry|@helpers"`: 104 passed (4 nursing
  flows, the 5 nursing screens x 3 viewports x 3 themes x 2 languages, route registry, helpers).
  Shared files touched: `errors.json` (5 codes), generated OpenAPI files, the three app routers
  (one `add_router` line each), `visits/permissions.py`, `visits/tests/test_contract.py`.
- 2026-10-09: Insurance claims on `feat/b-claims` (wave b, from `wave/b`): FEATURES 11.2-11.7.
  `/api/claims` (21 operations, every one behind a `claims.*` code: receivables by stage, aging,
  accrued lines, batches, per-line answers, rebill/write-off, short-pay write-off, Excel export
  and print data, payer payments with cheque clearing and reversal); screens `/claims`,
  `/claims/batches`, `/claims/new`, `/claims/$claimId`, `/claims/$claimId/print`,
  `/claims/payments`, `/claims/aging`. New domain rules `response_amount` and
  `allocate_to_claims` (Hypothesis), `record_payer_payment(claim_amounts=...)`, error codes
  `CLAIM_PARTIAL_INVALID` and `PAYER_ALLOCATION_CONFLICT` (ADR 0012). The export writes text
  starting with `=` as text (formula injection). Results: `make check` green (backend 1702
  passed, frontend 440 passed, lint, typecheck, no missing migrations, API contract in sync);
  `make e2e E2E_GREP="@claims|@responsive.*claims|route registry"`: 165 passed, 1 failed (the
  payment spec's amount locator, fixed), then `@claims` 3 of 3 passed.
  Follow-ups: per-payer export templates; a payer cash payment needs the recorder's own open
  shift (an accountant has none); rebill and write-off approval is the recording user with
  `claims.resolve_rejection` (no second person, ADR 0012).
- 2026-10-10: Wave b integration on `wave/b`: merged `feat/b-pharmacy` (FEATURES 5.12,
  8.1-8.10), `feat/b-lab` (9.1-9.8, ADR 0010), `feat/b-nursing` (3.4 for nurses, 10.1-10.3,
  10.5) and `feat/b-claims` (11.2-11.7, ADR 0012), in that order, `--no-ff`. Conflicts:
  `CHANGELOG.md` and `PROGRESS.md` (both sides kept at each merge), `errors.json` ar/en at the
  claims merge (pharmacy's 7 codes and claims' 2 kept; 385 codes, ar/en in parity). Pharmacy and
  lab merged without conflicts. Nursing's ADR renumbered 0011 (lab took 0010); claims already
  used 0012. Generated API files regenerated with `make api` after each conflicting merge (no
  drift); no migration clashes (only pharmacy added one, `pharmacy.0004`); OpenAPI schema
  class names stay unique. No integration fixes were needed. Results: `make check` green
  (backend 1820 passed, frontend 460 passed, ruff, mypy, eslint, prettier and tsc clean, no
  missing migrations, API contract in sync; shellcheck not installed here). Full `make e2e`:
  1548 passed, 2 failed, 3 did not run of 1553 (1.2 h). Both failures were flakes and passed
  in a rerun of `@clinic @responsive doctor states|patient-file` (27 of 27): the clinic doctor
  states case at 768 warm ar ran at midnight, when the visits its `beforeAll` made the day
  before left the doctor's queue (an empty queue; the three 1280 cases after it did not run
  because the file is serial); the patient-file 768 warm en case did not find the merge
  history, while the other 11 cases of the same route passed in the same run.
- 2026-10-10: Reports and the manager dashboard on `feat/c-reports` (wave c, from `wave/c`):
  FEATURES 4.5, 12.1-12.11 (ADR 0013). `/api/reports`: 14 reports, each `GET /<key>` and
  `GET /<key>/export` (.xlsx, formula-safe) behind one `reports.view_<area>` code, plus
  `/dashboard`; read-only queries in `apps/reports/queries.py` reusing the orders, claims, lab
  and pharmacy report queries; pure arithmetic in `domain/reports.py` (Hypothesis). Every money
  report is tested against `ledger.services` balances and postings; query counts do not grow
  with rows; reports never write. Screens `/reports`, `/reports/$reportKey`,
  `/reports/$reportKey/print`, and the manager dashboard at `/` (recharts, theme tokens).
  e2e fixture `reports_day`; specs `e2e/tests/reports/*.spec.ts` (@reports). Shared files
  touched: `apps/orders/services.py` (optional department on `report_*`, row cap 5,000),
  `apps/core/tests/test_permissions.py` (new code names), `components/DataTable.tsx` (totals
  row) and its test, `common.json` (`table.total`), `errors.json` (`REPORT_RANGE_TOO_LONG`),
  `frontend/package.json` (recharts 3.10.1), generated OpenAPI files. Results: lint (ruff,
  format, migrations, eslint, prettier), mypy and tsc (frontend, e2e) clean; frontend 474
  passed; API contract in sync; backend 1890 passed, 1 failed: `domain/tests/test_visit_machine.py`
  (Hypothesis stateful test of the payment engine found a pending-transfer rejection with
  `uncovered` 10.14 / a recovery row; domain code untouched by this branch, see follow-ups);
  71 report tests passed. `make e2e E2E_GREP="@reports|@responsive.*(reports|dashboard)|route
  registry|@auth sign in"`: 112 passed (twice, before and after the review fixes).
- 2026-10-10: Ops (wave c) on `feat/c-ops` from `wave/c`: FEATURES 1.8 (wizard), 8.13, 0.13,
  13.8, 13.9, 13.10 and the audit viewer (ADR 0014). Imports of patients, items with opening
  stock (goods receipt from `OPENING`) and prices (future version only); notifications with the
  bell and `manage.py notify_scan`; `/api/ops/status`, manual backup requests picked up by
  `infra/backup/backup-requests.sh`, the CSV data export, `/api/core/audit`; the maintenance loop
  runs `notify_scan` and `charge_bed_nights` as `BED_CHARGE_USER`. Results: `make check` green
  (backend 1895 passed, frontend 471 passed, lint, typecheck, no missing migrations, API contract
  in sync; shellcheck not installed here); `make infra-test` 55 checks passed; `make e2e
  E2E_GREP=@ops` 7 passed; the 4 admin system routes x 3 viewports x 3 themes x 2 languages plus
  the route registry 73 passed; the whole phone matrix with the bell in the top bar
  (`@responsive 375x812|@ops|route registry|shell`) 499 passed.
