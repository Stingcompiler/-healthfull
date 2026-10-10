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
- Contract test that every navigation permission code is registered by the backend or listed as pending
  for a later phase.
- Short phone tab bar labels (`nav:short`) so no label is cut at 360px; e2e test for it.
- Phase 1 domain core: pure, Hypothesis-tested rules for the service-line state machine (credited
  units and `open_quantity`, replacement lines), dated price-list versions, coverage splits, invoice
  and credit-note positions, allocation and pooled patient credit, shifts, transfer verification,
  double-entry ledger postings, payer claims, stock (units, FEFO, moves) and lab results.
- Phase 1 schema for every app, with pghistory audit and database guards: `line_guard`,
  `dispense_line_eligible`, `claim_line_guard`, `version_guard`, frozen and append-only tables,
  open-shift checks, a commit-time journal balance check and `truncate_guard`.
- Phase 1 services: ordering and perform-first authorizations, invoicing and credit notes with
  re-billing, payments with allocation, transfer confirmation and rejection, refunds, cash handovers,
  shift close with a frozen report, payer claims and payer payments (transfer, cheque, cash),
  dispensing with partial dispense and returns, lab samples, results, approval and amendments.
- Ledger account `CASH_SAFE` for cash in the safe, with a supervisor or between shifts; opening
  floats, handovers and the close sweep post through it, so a drawer's ledger cash is its expected
  cash.
- ADR 0006 (Phase 1 money and stock rules) with the differences found against the code.
- Arabic and English text for every error code the backend raises (`errors` namespace); a contract
  test checks that every backend code is translated and that each placeholder is sent by every
  raise of its code.
- `infra/db/`: database roles `hospital_owner` (owns the schema; migrations only) and `hospital_app`
  (DML only), created on the db image's first start; `infra/db-roles.sh` creates or repairs them on
  an existing install and `--verify` reports any stray grant. A one-off compose `migrate` service
  runs migrations as the owner before `app` and `maintenance` start.
- E2E base catalog in `seed_e2e` (idempotent): departments, clinic rooms, wards and beds, three
  more doctor accounts and weekly schedules, services of every kind in Arabic and English, a cash
  price list and one list per payer with a version effective from the seed day (plus a scheduled
  +10% cash version), payers `AMAN` (70%, one pre-approval rule, one exclusion), `NAKHEEL` (fixed
  copay) and `RAHMA` (ceiling), drugs and consumables with unit hierarchies and two batches each in
  the main store and the pharmacy, lab tests with reference ranges, tills and reason codes.
- `manage.py e2e_fixture <name> --json`: named data builders over the services (patient, coverage,
  visit, order, invoice, approve_invoice, open_shift, pay, close_shift, paid_visit, catalog) that
  act as a seed user with that user's permission; test databases only. Apps can add their own in
  `apps/<app>/e2e_fixtures.py`.
- `e2e/helpers/api.ts`: logged-in, CSRF-aware API clients per seed user (`apiAs`), calls by
  OpenAPI operation id, and typed factories (`createPatient`, `createVisit`, `orderLines`,
  `approveInvoice`, `pay`, `openShift`, `closeShift`, `paidVisit`, ...) that use real endpoints
  through per-module adapters when they exist and the fixture command otherwise; documented in
  `e2e/README.md`, covered by `e2e/tests/helpers.spec.ts` (`@helpers`).
- E2E route registry split per module: `e2e/module-routes/<module>.ts` lists a module's screens
  for the responsive matrix (loaded automatically), and a route with path parameters builds its
  data with `resolve`.
- Wave a, patients and visits (FEATURES 0.9, 1.1-1.6, 1.8, 2.1-2.7): patient list, registration with
  duplicate detection, profile, coverage, merge with a reason code, Excel/CSV patient import with
  preview and validation (`/patients/import`), patient results in the global quick search, visits,
  queue board, token slips, the kiosk waiting-room display `/display/queue`, and appointments with
  free slots and a doctor's day agenda.
- Wave a, administration (FEATURES 0.1-0.3, 5.2, 5.5, 11.1, 13.1-13.3): users with role guards,
  the role permission matrix, center profile and policies, departments, rooms, doctors and weekly
  schedules, reason codes, the service catalog, dated price-list versions with bulk updates and
  withdrawal of scheduled versions, payers with contracts, coverage rules and exclusions.
- Wave a, doctor and orders (FEATURES 3.1-3.9, 4.1, 4.2): doctor queue and visit workspace with
  vitals, allergies (with recorded overrides), conditions, diagnoses, referrals, favorites,
  prescriptions and the order builder; withdrawing an unstarted line and removing a diagnosis
  record a reason; doctors see no prices and hold no billing permission.
- Wave a, billing, payments and shifts (FEATURES 0.10, 4.4, 5.3, 5.4, 5.6, 5.8-5.11, 6.1-6.9,
  7.1-7.6): the cashier desk (patient lookup, visit billing, draft invoices with per-line payer,
  pre-approval references, line cancellation and discounts approved by a supervisor at the desk,
  approval with frozen prices), payments by cash, transfer, QR, card and patient credit with
  allocation, unique transfer references with a supervised override, the transfers queue with
  confirmation and late rejection, credit notes, refunds, perform-first authorizations, shifts
  with opening float, close with variance, frozen report and manager review, cash handovers to a
  named receiver or the safe, receipts with a QR check screen and A4/80 mm printing of receipts,
  invoices and the shift report (ADRs 0008, 0009).
- Wave b, pharmacy (FEATURES 8.1-8.10, 5.12): `/api/pharmacy` (46 operations) and the pharmacy
  screens: dispense queue of paid or authorized lines with a scanner-friendly search, dispense
  dialog with FEFO batches, other batches with a reason, pack units, item barcode scan and partial
  dispense (rest kept open, or cancelled and refunded with a supervisor at the counter); item
  master with pack units, barcodes and stock card; goods receipts with batches and suppliers;
  stock adjustments with approval; count sessions with variances posted by a manager; transfers
  with send, receive, shortage approval and cancel; expiry (30/60/90 days) and low-stock reports;
  walk-in sale draft invoice for the cashier. Adjustment requests and transfer drafts refuse more
  than the batch holds when made. Stock batches are "التشغيلة" in Arabic.
- Wave b, laboratory (FEATURES 9.1-9.8): `/api/lab` (25 operations) and the lab screens: the
  work list of paid or authorized tests with collect, receive and reject (a rejected sample's
  draft values are discarded), a 50 x 30 mm tube label, result entry per parameter with
  high/low/critical flags from sex- and age-specific ranges, the supervisor approval queue
  (approval names the draft revision it read, `RESULT_CHANGED`), amendments as new versions
  with the history kept, A4 result print in Arabic or English, "test cannot be performed" with
  a billing approver's credentials at the bench for a paid test (credit note, refund at the
  cashier), the test catalog editor and the turnaround report (median and 90th percentile).
  New permissions `lab.cancel_test` and `lab.view_reports` (ADR 0010).
- Wave b, nursing (FEATURES 3.4 for nurses, 10.1-10.3, 10.5): the procedure desk at `/nursing`
  (paid or authorized procedures as large tablet cards, one-tap done with a five-second undo
  window or with a note, done today), `/nursing/visits` (inpatients and today's visits) leading
  to the nursing chart (vitals, nursing notes, the visit's procedures and admission), and the
  bed board `/nursing/beds` (wards and beds with occupants, admit on an open or a new inpatient
  visit, transfer, discharge, bed out of service, posting the nights due as lines for the
  cashier); `/api/orders/procedures`, `/api/clinical/nursing`, `/api/visits/inpatient`,
  `manage.py charge_bed_nights` (ADR 0011).
- Wave b, insurance claims (FEATURES 11.2-11.7): `/api/claims` and the claim screens. Payer
  receivables by stage (accrued, claimed, accepted unpaid, rejected unresolved, collected), the
  batch builder per payer and period, Excel export (Arabic or English) and A4 print in the payer
  layout, the payer's answer per line (accepted, partial, rejected with reason), rejected parts
  rebilled to the patient or written off with a reason, short-paid amounts written off, payer
  payments by transfer, cheque (cleared later) or cash into the recorder's shift, allocated per
  claim or oldest first, reversal of a bounced payment, and aging by payer (0-30, 31-60, 61-90,
  over 90 days). Only `claims.*` holders reach any of it (ADR 0012).
- Wave c, patient portal (FEATURES 15.1, 15.2): `/api/portal` and the mobile-first screens under
  `/portal` (sign-in, home cards, appointments with online booking and cancellation, approved lab
  results with print, prescriptions and lab preparation, invoices and receipts), the public receipt
  check `/verify/<token>` behind the receipt QR, and a portal access code the cashier prints on the
  receipt. Web manifest and bundled icons, no service worker (ADR 0016).

### Security
- Patient portal (ADR 0016): its own session cookie (HttpOnly, SameSite=Strict, path `/api/portal`,
  hashed token, 15-minute idle and 4-hour limit) that opens no staff endpoint; receipt access codes
  stored hashed, expiring, revoked by a newer code and locked after wrong attempts; uniform refusals
  with equal hashing work, per-file-number lockout and per-address throttle; every other patient's
  row answers 404; the public receipt check needs an HMAC token, shows initials at most and is
  rate-limited; portal answers are `Cache-Control: no-store`.
- Django admin login uses the same credential check as the API (lockout, audit, session idle policy)
  and refuses accounts that must change their password; unlocking an account is an audited admin action
  with a reason (ADR 0005).
- Per-address login limit (429 `RATE_LIMITED`); unknown usernames lock like real ones (no 401/423
  enumeration oracle); wrong current passwords on change-password count toward the lockout.
- Request ids in audit rows are always generated by the server; forged `X-Forwarded-For` values are ignored.
- Password policy rejects the user's own name, the center name and common local words.
- `seed_e2e` refuses databases that are not `e2e_*` / `test_*`; `admin` is a normal admin-role user and
  the superuser is a separate break-glass account. e2e reads `E2E_DB_NAME` only.
- Web container runs Caddy as a non-root user; published ports bind to `BIND_IP`.
- Protected tables refuse `TRUNCATE` from any role that does not own them, and `pgtrigger`'s
  session switch can no longer turn the guards off. A table owner or superuser can still bypass
  triggers, so production must run the app as a non-owner role (ADR 0006, `infra/db/`).
- The app and the maintenance job connect as `hospital_app`, which cannot `TRUNCATE`, alter or drop
  tables, disable triggers or turn on `pgtrigger`'s ignore switch; the superuser is left to the db
  container and the backup sidecar, and each service blanks the passwords it must not hold.
  `PUBLIC` loses `CONNECT`/`TEMP` on the database and `CREATE` on schema `public`.

### Changed
- Nurses hold `visits.admit` by default (they record the admission on the doctor's decision);
  the Nursing menu entry shows to holders of any nursing permission. A cancelled visit takes no
  nursing notes (`VISIT_CANCELLED`).
- `MeOut.language` / `MeOut.theme` are `null` until the user chooses; the SPA keeps the device's choice.
- `money()` accepts only plain positional decimals (Arabic-Indic digits normalised).
- Phone touch targets are 44px and phone text inputs 16px; menus, selects and the command palette show a
  solid highlight bar; focus is a solid outline everywhere.
- DataTable opens rows with a real button (table and cards) and switches to cards by container width.
- Tablet rail can expand to labels; phone tab bar sizes to the modules a role has.
- Backups: kernel (`flock`) locks, catch-up of missed backups and restore tests, media failures give a
  `partial` run that keeps the dump, stale partial files and scratch databases cleaned up, atomic restore
  swap. `update.sh` writes `.env` atomically, records its state and checks the web container.
- `make check` and CI fail on missing migrations; CI uploads e2e server logs.
- ARCHITECTURE 4.4-4.9 rewritten to match the Phase 1 implementation: `in_progress` and credited
  units, price-list version dates, claim withdrawal on credit, refunds, handovers, the chart with
  `CASH_SAFE`, the frozen shift report, the database guard list and the non-owner database role.
- `update.sh` refuses to run (exit 2, naming `infra/db-roles.sh`) until the role passwords exist,
  reads the migration plan and migrates as the owner, and re-applies the role grants after the
  backup. `restore-dump.sh` hands a restored database to the owner and re-grants the app role
  before the swap. Role passwords: 16-128 characters of `A-Z a-z 0-9 . _ - ~`.

### Fixed
- OpenAPI components no longer collide between apps: visits publishes `VisitDepartmentOut`,
  `VisitDoctorOut` and `VisitRoomOut`, patients `PatientPayerOut`, so the admin screens type
  against the core and catalog shapes; a test fails on any repeated schema class name.
- The reason-code API and admin screen accept the `patient_merge` and `appointment_cancel`
  categories, with Arabic and English labels.
- The doctor billing access sweep (e2e) checks every billing and payments operation for a 403
  instead of reporting `fixme`.
- An empty credit note shows "Enter at least one unit to credit" under its lines (the message
  was filed under `qty.root` and never displayed).
- The helpers e2e spec no longer fails when a cashier spec has already added its `CSH70` payer.
- Billing `PatientSummaryOut` is published as `BillingPatientSummaryOut` so it no longer
  overwrites the clinic's patient summary in the OpenAPI contract.
- Cashier review (ADR 0008): a credit note is approved by someone other than its drafter
  (`CREDIT_NOTE_SELF_APPROVAL`) and a transfer confirmed by someone other than its taker
  (`SELF_CONFIRMATION_NOT_ALLOWED`); the transfers queue says when a closed shift's transfer needs
  the viewer's own open shift; the shift report lists desk line cancellations and voided drafts;
  money inputs refuse a third decimal; perform-first records who asked; one pager with the true
  total on the cashier queues; the payment method shows as selected; 80 mm print page rule fixed;
  credit-note quantities accept Arabic-Indic digits; 44px tabs on phones; Arabic wording fixes.
- Patient names are never truncated (four-part Sudanese names wrap instead of losing the family name).
- Error messages with placeholders (amounts, dates, bed codes, units) show their values:
  `translateError` passes the error's `details` to i18next for interpolation only.
- Arabic initials skip the article "ال" and stay separate letters; KPI trend values are read by screen
  readers; IDs inside translated text keep their order (`bidi` formatter); Arabic role and length
  messages corrected.
- Unknown `/api/` paths answer JSON 404 even without a CSRF token; `DoesNotExist`, Django
  `ValidationError` and `IntegrityError` map to 404 / 422 / 409.
- Transactional tests no longer wipe the migration seed for later runs (`--reuse-db`).
- Generic `DEBUG` / `SECRET_KEY` variables (e.g. Playwright's `DEBUG=pw:api`) no longer reconfigure Django.
- Patient names in the other script (an English name in the Arabic UI and the reverse) were cut at their
  beginning when too long; each name line now takes its own direction and stays aligned with the card.
