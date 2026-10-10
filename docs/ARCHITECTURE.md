# Architecture and Conventions

Binding for every contributor, human or agent. Product rules live in `DECISION.md`, `FLOW.md`, `FEATURES.md`. Stack rationale in `STACK.md`. When this file and those disagree on product behavior, `FLOW.md` wins; on code conventions, this file wins.

## 1. Repository layout

```
backend/                 Django 5.2 LTS + django-ninja, Python 3.12, managed by uv
  config/                settings.py, urls.py, wsgi.py, asgi.py
  api/                   NinjaAPI assembly, error mapping, shared schemas (Page, ErrorOut)
  domain/                PURE Python rules. No django imports. Hypothesis tests in domain/tests/
  apps/<module>/         Django apps: models, services, api (router), schemas, admin, tests
frontend/                React 19 + Vite + TypeScript 5.9 strict + Tailwind v4 + shadcn/ui
  src/app/               router, providers, shell
  src/design/            tokens.css (themes), status colors
  src/components/ui/     shadcn primitives (generated, lightly edited)
  src/components/        shared app components (cards, DataTable, dialogs, MoneyText...)
  src/i18n/              i18next setup; locales/{ar,en}/<namespace>.json
  src/lib/api/           openapi-fetch client + generated schema.d.ts
  src/features/<module>/ pages, components, hooks, routes.tsx per module
  src/portal/            patient portal (mobile-first), same SPA, /portal/*
e2e/                     Playwright tests, fixtures, responsive helpers
agent/                   local device agent (Python, PyInstaller)
infra/                   Dockerfiles, compose, Caddyfile, pgbackrest, update.sh, backup scripts
docs/                    decisions, ADRs (docs/adr/NNNN-title.md), runbooks/, guides/ (user guides per role)
scripts/                 dev helper scripts
Makefile                 the only entry point for common commands
```

## 2. Commands (Makefile targets)

| Target | Does |
|---|---|
| `make setup` | `uv sync` in backend, `pnpm install` in frontend and e2e, create dev DB |
| `make dev` | backend on `$BACKEND_PORT` + frontend on `$FRONTEND_PORT`; when unset, `scripts/ports.sh` derives them per worktree (section 3) |
| `make test` | backend pytest (incl. Hypothesis) + frontend vitest |
| `make lint` | ruff check + ruff format --check + eslint + prettier check |
| `make typecheck` | mypy (strict on domain/) + tsc --noEmit |
| `make api` | export OpenAPI to `frontend/openapi.json` and regenerate `frontend/src/lib/api/schema.d.ts` |
| `make e2e` | reset e2e DB, seed, start servers on free ports, run Playwright |
| `make seed` | load demo dataset into dev DB |
| `make check` | lint + typecheck + test + api drift check. Must be green before any commit to main |
| `make infra-test` | shell lint + `infra/tests/run.sh`: update.sh (fake docker), roles, backup/restore and the restore-from-scratch drill (local Postgres 16; the drill also needs `backend/.venv`) |

## 3. Parallel-safe local environment

Several checkouts (git worktrees) may run at once. Never hardcode DB names or ports.

- DB connection from env: `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `DB_NAME` (default `hospital_dev`). Local dev uses the Homebrew Postgres 16 socket (no password).
- Test DB name is `test_hospital_<h>` and e2e DB is `e2e_hospital_<h>` where `<h>` = first 8 hex chars of sha1 of the absolute repo root path. Computed in settings and in e2e config. This isolates worktrees automatically.
- Ports: `BACKEND_PORT` and `FRONTEND_PORT` env vars. When unset, `scripts/ports.sh` derives them from `<h>` (20000 + int(h,16) % 20000, and +1) for both `make dev` and `make e2e`; the e2e runner steps past busy ports (+2) so it can run beside `make dev`.

## 4. Backend conventions

### 4.1 Apps (all pre-registered in INSTALLED_APPS from Phase 1)

| App | Owns |
|---|---|
| `core` | User (custom, AbstractUser), Role, RolePermission matrix, permission registry, CenterProfile, Policy (singleton settings), Sequence (document numbering), ReasonCode, Department, Room, DoctorProfile, Notification |
| `patients` | Patient, PatientCoverage, merge history |
| `visits` | Visit, QueueEntry, Appointment, DoctorSchedule |
| `catalog` | Service (kinds: consultation, lab, procedure, drug, consumable, bed), PriceList, PriceListVersion, PriceItem, Payer, CoverageRule, Exclusion |
| `clinical` | Allergy, ChronicCondition, ClinicalNote, Diagnosis, Icd10Code, Vitals, Referral, OrderSet, NursingNote |
| `orders` | ServiceLine (the stateful order line), PerformAuthorization |
| `billing` | Invoice, InvoiceLine (frozen), CreditNote, CreditNoteLine |
| `payments` | Shift, Payment, Allocation, Refund, CashHandover |
| `ledger` | Account (fixed chart), JournalEntry, JournalLine |
| `pharmacy` | Item, UnitConversion, Store, Batch, StockMove, Dispense, DispenseLine, GoodsReceipt(+Line), StockAdjustment, StockCount(+Line), Supplier |
| `lab` | LabTest, LabParameter, ReferenceRange, Sample, ResultSet, ResultVersion, ResultValue |
| `claims` | Claim, ClaimLine, PayerPayment, PayerPaymentAllocation |
| `reports` | no models; read-only query services |
| `portal` | PortalAccessCode, portal auth |
| `imports` | ImportJob, ImportRow (Excel preview/confirm) |
| `ops` | BackupRun, RestoreTest, UpdateRun (written by `infra/update.sh` through `manage.py record_update`), BackupRequest, DataExport, health checks, status page, `manage.py integrity_check` (`apps/ops/integrity.py`) |

### 4.2 Layering (strict)

```
api (ninja router)  ->  services  ->  domain (pure)  
                       services  ->  models
```

- Routers do: auth, permission check, schema in/out, call ONE service function. No business logic in routers.
- Services (`apps/<m>/services.py` or `services/` package) own transactions (`transaction.atomic`), row locks (`select_for_update`), ledger posting, audit context, and call domain functions for every rule and calculation.
- Domain functions take and return plain dataclasses / Decimals / enums. They raise `domain.errors.DomainError(code, message, **details)`.
- Cross-app calls go through the other app's `services` module, never by writing its models directly.

### 4.3 Money

- Type: `decimal.Decimal`, 2 places, `ROUND_HALF_UP`, via `domain.money` helpers (`money()`, `q()`). DB: `DecimalField(max_digits=14, decimal_places=2)`. Never float. Currency is SDG, single currency.
- Splits always compute one side and derive the other by subtraction so parts sum exactly to the whole.
- API serializes money as strings (`"10000.00"`). Frontend formats with `Intl.NumberFormat` and never does arithmetic beyond display totals.

### 4.4 The service line (FLOW.md section "حالات سطر الخدمة")

A `ServiceLine` is one ordered unit of service on a visit. It has two orthogonal status fields plus a derived display state. Rules live in `domain/service_line.py` (property-tested); every change goes through `apps/orders/services.py`; the DB trigger `line_guard` repeats them (4.9). Decisions behind this section: ADR 0006.

| Field | Values |
|---|---|
| `billing_status` | `unbilled` → `invoiced` ⇄ `settled`; `invoiced`/`settled` → `credited` (every unit credited by approved credit notes) |
| `fulfilment_status` | `pending` → `in_progress` (optional) → `performed`; `pending`/`in_progress` → `cancelled` |
| `authorization` | nullable FK to PerformAuthorization (perform-first exception, revocable) |
| `quantity` / `performed_quantity` | units ordered / units actually given when a line is closed partly performed |

Derived `state` for UI and reports: `cancelled` if fulfilment cancelled; else `performed` if performed; else `paid` if settled; else `invoiced` if invoiced; else `requested`. The doctor sees `requested`, `paid` (settled or authorized), `in_progress`, `done`, `cancelled`, never prices.

Rules:
1. Eligible (work lists, start, perform, dispense) ⇔ fulfilment `pending|in_progress` AND (billing `settled` OR an unrevoked authorization of the same visit). Pay-first is always on (`Policy.default_pay_first` is fixed true); perform-first exists only as a documented authorization.
2. `settled` ⇔ invoiced AND patient outstanding on that line = 0 (zero patient share settles at invoice approval). A transfer rejection or a payer rebill can take a settled line back to `invoiced`.
3. `in_progress` is entered by the first work step (sample collected, first part dispensed) through `start_line`, needs eligibility, and never goes back to `pending`. Procedures go straight to `performed`. An authorization cannot be revoked while unpaid work under it is in progress; work performed before a revocation stays covered.
4. Credited units are never given: `open_quantity = ordered − credited − given`. A credit of an open line takes back only ungiven units (`CREDIT_EXCEEDS_UNGIVEN`); a performed quantity is at most ordered − credited.
5. Cancelling an unbilled line cancels it and drops it from draft invoices. An invoiced or settled line is cancelled only by a credit note (`CREDIT_NOTE_REQUIRED`), approved by a holder of `billing.approve_credit_note`: when approved credits cover every unit the line becomes `credited`, and an open line also `cancelled`. Patient money on it becomes patient credit with a refund request opened. A line with dispensed units is never cancelled: the given units are performed and only the rest is closed (`cancel_line_remainder`); an unbilled line is then invoiced for the performed quantity.
6. `performed` and `cancelled` are terminal. A performed line is only credited financially. One exception (ADR 0018): an unbilled bed night of an admission cancelled in error is voided (`void_in_error`, second-person approval; `line_guard` allows only that edge). A correction re-bills through a replacement line (`replacement()`): a fresh requested line for a cancelled original, or an unbilled line already performed under a new authorization for a performed original.
7. Every transition records actor and timestamp, and a reason where required; DB checks require the documenting columns of `in_progress`, `performed`, `cancelled`, `invoiced` and `credited`.

### 4.5 Invoices

- `Invoice.status`: `draft` → `approved`; `void` only for drafts. Approved invoices are immutable (DB trigger). InvoiceLine has `frozen` set true at approval; trigger blocks UPDATE/DELETE when `OLD.frozen`.
- Invoice lines are created only from the visit's `unbilled`, open service lines. No free-amount lines.
- A draft shows today's prices; at approval each line is priced again and frozen from the PriceListVersion effective on the approval date (`Invoice.priced_on`) for the line's payer price list: unit price, quantity, gross, discount, payer (nullable = cash), payer_share, patient_share.
- Price list versions start tomorrow at the earliest, one per date (`PRICE_VERSION_BACKDATED`, `PRICE_VERSION_DATE_TAKEN`); only the first version of a list with nothing effective may start today. A version's prices change only before it starts. DB `version_guard` and `item_guard` refuse a version that would reprice frozen invoices and any change to a version a frozen line used.
- Coverage per line (`domain/coverage.py`): payer rule = percentage, fixed patient copay, or payer ceiling; exclusions route 100% to patient. `payer_share` computed, `patient_share = gross − discount − payer_share`, never negative.
- Discounts apply to the patient share only, limited by role policy, reason mandatory.
- Corrections only by CreditNote (approved by someone other than its drafter, `CREDIT_NOTE_SELF_APPROVAL`, ADR 0008; immutable, number `CN`) linked to the original lines. A credit line credits whole units; partial credits use cumulative rounding so all credits of a line add up to it exactly. Approval posts the mirror entry, applies 4.4 rule 5, and de-allocates the patient money the credited lines held above their new due into patient credit (it never drifts onto other lines). `rebill=True` creates replacement lines.
- A payer share already on a claim is credited only by withdrawing its claim line: always while the payer has not answered; after an answer only when nothing was paid, resolved or written off and the credit covers the whole claimed amount. Otherwise `CLAIM_LINE_LOCKED`.
- A rejected payer share rebilled to the patient adds to the patient due of the original invoice line; the invoice itself does not change.

### 4.6 Payments, allocation, shifts

- A cashier has at most one open Shift (lock plus partial unique index). Money is taken, refunded or handed over only in the actor's own open shift; every money row that names a shift requires it open (trigger).
- `Payment.method`: `cash`, `bank_transfer`, `qr`, `card`, `patient_credit`. Bank/QR/card carry `bank` + `reference`. The reference is unique per bank after normalization (`reference_norm`); a duplicate needs a holder of `payments.override_duplicate` and a reason, and is stored flagged.
- `Payment.verification`: cash and spent credit = `confirmed`; others start `pending`. Confirming needs `payments.confirm_transfer` and a note saying what was checked (reason, approver, time stored), by someone other than the payment's taker or its shift's cashier (`SELF_CONFIRMATION_NOT_ALLOWED`, ADR 0008). Rejecting (pending or confirmed) needs `payments.reject_transfer` and a reason code. Pending money settles service lines (so service proceeds) but is NEVER reported as confirmed collection.
- Allocation rows are append-only and signed (reversals and de-allocations are negative rows). A payment's allocations ≤ its amount; the remainder is patient credit, one pooled balance per patient file (ledger `PATIENT_CREDIT`). Spendable credit excludes the unallocated part of pending transfers. Allocation to an invoice applies to its lines in line order to decide which lines are settled. Partial payment of an invoice only if `Policy.allow_partial_payment`.
- Rejecting a transfer reverses its allocations (lines may return to `invoiced`), recovers credit it funded that was spent (newest first), and takes its amount out of patient credit. A confirmed transfer's remainder is covered by spendable credit only, never by pending money; a pending transfer's rejection recovers nothing (ADR 0015). What cannot be recovered (refunded in cash) stays as a negative credit balance (`uncovered`) and managers are notified. If the original shift is closed, the rejection books a negative payment linked to the original in the actor's current open shift; without one it is refused (`SHIFT_NOT_OPEN`), so a user with no till (an accountant) hands it to a supervisor with an open shift (ADR 0008).
- Refund: cash only, from credit created by an approved credit note (less earlier refunds of it) and within spendable credit. Requested by one person, approved by another (`SELF_APPROVAL_NOT_ALLOWED`, DB check), paid from the paying user's own open shift when its expected cash covers it. Overpayments are not refundable; they stay as credit.
- Handover (`next_shift`, `safe`, `bank_deposit`, `supervisor`): at most the drawer's expected cash. Cash for the next shift is in transit until its cashier receives it; an unreceived handover may be cancelled with a reason while the sending shift is open. A shift cannot close while cash handed to it waits (`HANDOVER_PENDING`).
- Shift close: expected cash = opening float + cash payments + payer cash − cash refunds paid − handovers out (not cancelled) + handovers in (received). Counted cash is entered; a non-zero variance needs a variance reason (and a note when the reason asks for one) and alerts managers. The report is frozen in `Shift.close_report` and served from it; a closed shift is immutable (trigger) and later effects show in the shift where they are booked. A manager other than the cashier reviews it.
- Merged patient files (FEATURES 1.4): a merge moves no money. Balances, spendable credit and open invoices of a person sum all files; new money is taken on the surviving file only; refunds are opened per file the money came from.

### 4.7 Ledger (append-only double entry)

Fixed chart in `domain/ledger.py` and seeded `ledger.Account` rows (`apps/ledger/chart.py`):

| Code | Meaning | Dimensions |
|---|---|---|
| `CASH` | cash in a drawer | shift |
| `CASH_SAFE` | cash in the safe, with a supervisor, or in transit between shifts | |
| `BANK_PENDING` | transfers awaiting verification, uncleared payer cheques | |
| `BANK` | verified bank money | |
| `AR_PATIENT` | patient receivable | patient, invoice |
| `AR_PAYER` | payer receivable | payer, invoice |
| `PATIENT_CREDIT` | money held for patient (liability) | patient |
| `REVENUE` | service revenue | department, service kind |
| `DISCOUNT` | discounts given (contra revenue) | |
| `WRITE_OFF` | payer rejections and short payments written off | payer |
| `CASH_OVER_SHORT` | shift variances | shift |

Postings (each a balanced JournalEntry with `source_type`, `source_id` and, when there is one, the open shift it is booked in; late effects follow 4.6):
- Invoice approved: Dr AR_PATIENT (patient share), Dr AR_PAYER (payer share), Dr DISCOUNT (discount) / Cr REVENUE (gross).
- Payment received: Dr CASH (shift) or BANK_PENDING / Cr PATIENT_CREDIT. Spending patient credit posts nothing; only its allocations post.
- Allocation (signed): Dr PATIENT_CREDIT (paying file) / Cr AR_PATIENT (invoice's file); a negative row posts the opposite.
- Transfer confirmed: Dr BANK / Cr BANK_PENDING. Rejected: negative allocation rows first, then Dr PATIENT_CREDIT / Cr BANK_PENDING (or BANK if it was confirmed).
- Credit note: Dr REVENUE / Cr AR_PATIENT, Cr AR_PAYER, Cr DISCOUNT (mirror of the credited shares), then de-allocation rows.
- Refund: Dr PATIENT_CREDIT / Cr CASH (paying shift).
- Shift opened: Dr CASH / Cr CASH_SAFE (opening float). Handover: Dr CASH_SAFE (safe, supervisor, next shift) or BANK (deposit) / Cr CASH. Received by a shift: Dr CASH / Cr CASH_SAFE. Cancelled: the opposite of the handover.
- Shift closed: variance CASH vs CASH_OVER_SHORT, then the counted cash Dr CASH_SAFE / Cr CASH. An open shift's CASH equals its expected cash; a closed shift's CASH is zero.
- Payer rejection rebilled: Dr AR_PATIENT / Cr AR_PAYER. Written off (a rejection or an accepted amount short-paid): Dr WRITE_OFF / Cr AR_PAYER. Payer payment (always fully allocated; no payer advance account): Dr BANK (transfer), BANK_PENDING (cheque) or CASH (recording user's open shift) / Cr AR_PAYER. Cheque cleared: Dr BANK / Cr BANK_PENDING. Reversed (bounced transfer or cheque): the opposite, from where the money sits; payer cash is never reversed.

`apps/ledger/services.post` is the only writer. JournalEntry and JournalLine are append-only; a deferred trigger refuses an entry with fewer than two lines or debits ≠ credits at commit; a line trigger checks the account's dimensions. Inventory is tracked by StockMove, not the money ledger.

### 4.8 Stock

- StockMove is the append-only stock ledger: `(item, batch, store, qty_base signed, kind, source)`. Kinds: receipt, dispense, adjustment, transfer_out, transfer_in, count_correction, return. `StockBalance` (one row per batch and store) is maintained only by the `stock_balance` trigger and has `CHECK (qty_base >= 0)`.
- Quantities are whole base units (e.g. tablet). UnitConversion defines box→strip→tablet factors.
- Stock never goes negative: services lock the StockBalance rows they read `FOR UPDATE` in id order and check the whole set of moves with `domain.stock.apply_moves` before inserting them; the CHECK is the backstop.
- A batch is usable through its expiry date (`expiry >= today + min_days_left`, default 0). Dispense suggests FEFO (earliest expiry, usable, positive on-hand); another batch needs `pharmacy.override_batch` and a reason; an expired batch is never dispensed. Expired goods are refused at receipt.
- Dispense only eligible drug and consumable lines (4.4 rule 1) and at most their open units (DB `dispense_line_eligible`). The first part moves a line to `in_progress`; the rest stays open or is closed with a refund (`Policy.partial_dispense_remainder`, or per request); when every open unit is given the line is performed.
- Returns put units back with a reason, at most dispensed − returned. Transfers write a move out and a move in; a shortage at receipt needs an approval. Adjustments need an approver; stock counts turn differences into count_correction moves.
- Stock decrements at dispense, never at invoicing.

### 4.9 Immutability, database guards and audit

- `django-pgtrigger` guards (each raises `<CODE>: <message>`):
  - Append-only: JournalEntry/Line, Allocation, StockMove, Dispense/DispenseLine/DispenseReturn, PayerPaymentAllocation, ShiftReview, PatientMerge, AuthEvent.
  - Frozen by status: approved Invoice/InvoiceLine and CreditNote/CreditNoteLine (lines only under a draft parent), closed Shift, final Refund and rejected Payment, money fields of Payment and PayerPayment, approved/amended ResultVersion and its values, closed/void Claim, posted stock documents, PriceListVersion/PriceItem once a frozen line used them.
  - Transition guards: `line_guard` (4.4), `claim_line_guard` (claim line edges, never claims more than accrued), `dispense_line_eligible` (4.8), `authorization_guard`, `payment_verification_forward`, `refund_forward`, `handover_guard`, `version_guard`.
  - `shift_must_be_open` on every row that names a shift; the deferred balance trigger on journal entries.
  - `truncate_guard` on the 22 money, claim, service-line, stock and lab result tables: `TRUNCATE` is refused unless the session role is a member of the table owner.
  - `pgtrigger`'s ignore switch is replaced after every `migrate` by a function that never ignores a trigger.
- Database roles: production runs the application as a non-owner role with DML grants only; the owner runs migrations. The table owner or a superuser can still truncate or disable triggers, so the guards hold only under that split (ADR 0006 (m); roles set up by `infra/db/`).
- Verification: `manage.py integrity_check` (read-only snapshot, runs as the app role) re-derives what the guards protect: trial balance zero and every entry balanced, AR_PATIENT per invoice = document position, AR_PAYER per payer = claims documents, shift CASH = expected cash (zero once closed), stock never negative and balances = moves, no orphan allocations. The restore drill (`infra/backup/restore-drill.sh`) runs it on every rebuilt database (ADR 0020).
- `django-pghistory` tracks every mutable model with context (user id, request id, reason). Services set context via `pghistory.context(user=..., reason=...)`. Middleware attaches the request user.

### 4.10 Permissions

- Permission codes are strings `"<app>.<action>"` registered in `apps/core/permissions.py` with default roles. `RolePermission` rows override defaults (editable matrix).
- Roles: `receptionist`, `doctor`, `cashier`, `cashier_supervisor`, `pharmacist`, `lab_tech`, `lab_supervisor`, `nurse`, `accountant`, `manager`, `admin`, and `display` (the waiting-room kiosk account: only `visits.view_display`, ADR 0019). A user may hold several roles.
- Routers enforce with `@require_perm("billing.approve_invoice")` (403 `PERMISSION_DENIED`). `GET /api/auth/me` returns the user's roles and effective permission codes; the frontend uses them only to hide UI, never as security.
- Doctors never get billing permissions by default.

### 4.11 API

- Mounted at `/api/`. One router per app: `/api/auth`, `/api/core`, `/api/patients`, `/api/visits`, `/api/catalog`, `/api/clinical`, `/api/orders`, `/api/billing`, `/api/payments`, `/api/pharmacy`, `/api/lab`, `/api/claims`, `/api/reports`, `/api/imports`, `/api/ops`, `/api/portal`.
- Auth: Django session cookie + CSRF (`X-CSRFToken` header from `csrftoken` cookie). `GET /api/auth/csrf` sets the cookie. Portal uses its own session key and router auth.
- Schemas: Pydantic via ninja `Schema`. Names `<Thing>In`, `<Thing>Out`, `<Thing>Patch`. Operation ids `<app>_<verb>_<thing>` (stable; they become frontend function names).
- Lists: `?page=1&page_size=25&q=...` → `{items, count, page, page_size}`.
- Errors: JSON `{code, message, details}`. 400/422 validation, 401 unauthenticated, 403 `PERMISSION_DENIED`, 404 `NOT_FOUND`, 409 domain rule violation (`code` from DomainError, e.g. `INVOICE_FROZEN`, `SHIFT_NOT_OPEN`, `DUPLICATE_REFERENCE`, `STOCK_INSUFFICIENT`). Frontend maps `code` to translated text via the `errors` namespace.
- Bilingual data fields are `name_ar` and `name_en`; the UI picks by current language with fallback.
- OpenAPI exported by `manage.py export_openapi` to `frontend/openapi.json` (committed). CI fails if it drifts.

## 5. Frontend conventions

### 5.1 Design tokens and themes

- All colors are CSS variables in `src/design/tokens.css`, mapped into Tailwind v4 `@theme`. Components use semantic utilities only (`bg-surface`, `text-fg`, `text-muted`, `border-border`, `bg-primary`, `text-primary-fg`, status colors). No raw hex or Tailwind palette colors in components.
- Themes via `<html data-theme="light|dark|warm">`, persisted per user (server profile) with localStorage as first-paint cache. Respect `prefers-color-scheme` only when the user has no saved choice.

| Token | light | dark | warm |
|---|---|---|---|
| `--primary` | `#0D9488` | `#2DD4BF` | `#4F46E5` |
| `--bg` | `#F8FAFC` | `#0B1220` | `#FAF8F5` |
| `--surface` | `#FFFFFF` | `#111A2E` | `#FFFFFF` |
| `--fg` | `#0F172A` | `#E2E8F0` | `#1C1917` |

Semantic: success emerald, warning amber, danger rose, info sky, each with `-bg`/`-fg` pairs per theme meeting WCAG AA.
Service line state colors (`--state-*`): requested slate, invoiced blue, paid light green, performed dark green, cancelled rose, pending-verification amber.

- Typography: IBM Plex Sans Arabic (Arabic) and Inter variable (Latin) from `@fontsource` packages, bundled. Tabular numerals (`font-variant-numeric: tabular-nums`) in money and tables.
- Radius 12px cards, 8px inputs/buttons. Card padding 16px mobile / 20px ≥md. Light theme: soft shadow; dark: 1px border, no shadow.

### 5.2 Direction and language

- i18next with namespaces per module (`common`, `errors`, `auth`, `nav`, plus one per feature). Both `ar` and `en` files must have identical key sets (a vitest test enforces this).
- `<html lang dir>` updates instantly on switch; Radix `DirectionProvider` wraps the app. Use logical utilities only (`ms-`, `me-`, `ps-`, `pe-`, `start-`, `end-`, `text-start`). Never `ml-/mr-/pl-/pr-/left-/right-` in app code. Directional icons (chevrons, arrows) flip in RTL.
- IDs, numbers and codes inside translated text use the `bidi` formatter (`{{fileNo, bidi}}`), which isolates them (FSI/PDI) so `2026-00412` never renders as `00412-2026` in Arabic. Components that render an ID on its own wrap it in `<bdi>`.
- No hardcoded user-visible strings in components (eslint rule `i18next/no-literal-string` in `src/features`, `src/components`, `src/portal`).
- Dates and numbers via `Intl` with the current locale; Arabic UI uses Arabic-Indic digits only if the center setting says so (default Latin digits, which Sudanese clinics commonly use).

### 5.3 Responsive

- Breakpoints tested: 375×812 (phone), 768×1024 (tablet), 1280×800 (desktop).
- `DataTable` renders a table ≥md and a card list <md. No horizontal page scroll at any breakpoint (e2e asserts `document.documentElement.scrollWidth <= innerWidth`).
- AppShell: sidebar ≥lg, collapsible rail md, bottom/drawer nav on phone.

### 5.4 Shared components (must exist before feature work)

`AppShell`, `PageHeader`, `KpiCard`, `PatientCard` (name, age, sex, file no, allergies prominent), `ServiceLineCard`, `AlertCard`, `EmptyState` (with suggested action), `StatusBadge` (all service-line states + payment verification), `MoneyText`, `DateText`, `DataTable` (responsive), `ReasonDialog` (reason code + free text), `ConfirmDialog`, `FormField` family, `SearchInput` (debounced), `ThemeSwitcher`, `LanguageSwitcher`, `Can` (permission gate), `Kbd` + shortcut hook.

### 5.5 Data and routing

- `openapi-fetch` typed client from generated `schema.d.ts`; TanStack Query hooks live in `features/<m>/api.ts`.
- Code-based TanStack Router. Each feature exports `routes(parent)` from `features/<m>/routes.tsx`; `src/app/routes.ts` already imports every feature (pre-registered) so feature work never edits shared routing files. Nav entries per feature in `features/<m>/nav.ts`, aggregated centrally and filtered by permission.
- Forms: react-hook-form + zod; server `code` errors shown via the `errors` namespace.

## 6. Testing

| Layer | Tool | Rule |
|---|---|---|
| Domain | pytest + Hypothesis | Every invariant has a property test. Money-moving functions are test-first |
| Services | pytest-django on real Postgres | Every transition, permission, and trigger protection tested, including that DB triggers reject direct UPDATE/DELETE |
| API | ninja TestClient | Happy path + permission denied + domain error code per endpoint |
| Frontend | vitest + Testing Library | Components with logic, i18n key parity |
| Infra | bash + fake docker + local Postgres (`make infra-test`) | `update.sh` control flow and its UpdateRun record, roles, backup/restore, restore-from-scratch drill on a database seeded through the services |
| E2E | Playwright (chromium) | Each feature's main flow at 3 viewports; overflow check for every route × 3 viewports × 3 themes × 2 languages; screenshots to `artifacts/screens/<route>-<viewport>-<theme>-<lang>.png` for (ar,light), (en,dark), (ar,warm) |

E2E seed users (one per role, plus three more doctors) are created by `manage.py seed_e2e`; credentials live in `e2e/fixtures/users.ts` and `backend/apps/core/management/commands/seed_e2e.py` only (test values, never real). The same command seeds the base catalog (`backend/apps/core/e2e/catalog.py`: departments, doctors' schedules, services, price lists, payers and coverage rules, stock, lab tests, wards and beds). Specs build further data with the factories in `e2e/helpers/api.ts`, which call the real endpoints through registered adapters when they exist and otherwise `manage.py e2e_fixture` (builders over the services, test databases only); see `e2e/README.md`.

## 7. Git workflow (see `.claude/skills/ship-feature/SKILL.md`)

Branch `feat/<phase>-<slug>` → Conventional Commits → `make check` + e2e for touched areas → self-review checklist → fix → push → PR → CI green → squash merge to `main` → update `CHANGELOG.md` and `PROGRESS.md`.

## 8. Things that are never allowed

- Business logic in routers or React components.
- Floats for money. Raw SQL updates to protected tables outside migrations.
- Any runtime fetch to the internet (fonts, CDNs, analytics). The app must work on an isolated LAN.
- Raw colors, physical-direction utilities, or hardcoded strings in UI code.
- Features tagged P2 or Later before Phase 8 is complete.
- Weakening a test to make it pass. Fix the code or record an ADR explaining the rule change.
