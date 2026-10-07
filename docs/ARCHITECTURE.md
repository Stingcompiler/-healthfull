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
docs/                    decisions, ADRs (docs/adr/NNNN-title.md), runbooks
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
| `ops` | BackupRun, RestoreTest, health checks |

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

A `ServiceLine` is one ordered unit of service on a visit. It has two orthogonal status fields plus a derived display state.

| Field | Values |
|---|---|
| `billing_status` | `unbilled` → `invoiced` → `settled`; `credited` (removed by credit note) |
| `fulfilment_status` | `pending` → `in_progress` (optional, e.g. sample received) → `performed`; or `cancelled` |
| `authorization` | nullable FK to PerformAuthorization (perform-first exception) |

Derived `state` for UI and reports: `cancelled` if fulfilment cancelled; else `performed` if performed; else `paid` if settled; else `invoiced` if invoiced; else `requested`.

Rules (implemented in `domain/service_line.py`, property-tested):
1. Eligible for work lists ⇔ fulfilment `pending|in_progress` AND (billing `settled` OR authorization present).
2. `settled` ⇔ invoiced AND patient outstanding on that line = 0 (lines with zero patient share settle at invoice approval).
3. Cancelling a line that is `invoiced` or `settled` requires a credit note line; if patient money was allocated it becomes patient credit, refundable.
4. `performed` and `cancelled` are terminal for fulfilment. A performed line cannot be cancelled; it can only be credited financially with a reason.
5. Every transition records actor, timestamp, and reason where required.

### 4.5 Invoices

- `Invoice.status`: `draft` → `approved`; `void` only for drafts. Approved invoices are immutable (DB trigger). InvoiceLine has `frozen` set true at approval; trigger blocks UPDATE/DELETE when `OLD.frozen`.
- Invoice lines are created only from the visit's `unbilled` service lines. No free-amount lines.
- Each line freezes: unit price from the PriceListVersion effective on approval date for the line's payer price list, quantity, gross, discount, payer (nullable = cash), payer_share, patient_share.
- Coverage per line (domain/coverage.py): payer rule = percentage, fixed patient copay, or payer ceiling; exclusions route 100% to patient. `payer_share` computed, `patient_share = gross − discount − payer_share`, never negative.
- Discounts apply to the patient share only, limited by role policy, reason mandatory.
- Corrections only by CreditNote (approved, immutable) linked to the original invoice lines.

### 4.6 Payments, allocation, shifts

- A cashier must have exactly one open Shift to take or refund money. Payments and refunds belong to a shift.
- `Payment.method`: `cash`, `bank_transfer`, `qr`, `card`, `patient_credit`. Bank/QR/card carry `bank` + `reference`. Unique constraint on `(bank, reference)` for non-cash methods; override needs `cashier_supervisor` permission + reason (stored, and the duplicate flagged).
- `Payment.verification`: cash = `confirmed`; others start `pending` and move to `confirmed` or `rejected` by a user with `payments.confirm_transfer`. Pending money settles service lines (so service proceeds) but is NEVER reported as confirmed collection.
- Allocation: payment amount → invoices (patient side). Sum of allocations ≤ payment amount; remainder is patient credit. Allocation to an invoice applies to its lines in line order to decide which lines are settled.
- Partial payment of an invoice allowed only if `Policy.allow_partial_payment`.
- Rejecting a confirmed-or-pending transfer reverses its allocations (lines may return to `invoiced`, notification to manager). If the original shift is closed, the reversal posts to the acting user's current open shift, linked to the original.
- Refund: only from patient credit created by a credit note or cancellation; supervisor approval; paid from the current shift.
- Shift close: expected cash = opening float + confirmed cash in − cash refunds − cash handovers out; counted cash entered; variance requires explanation when non-zero; closed shift immutable (trigger).

### 4.7 Ledger (append-only double entry)

Fixed chart in `domain/ledger.py` and seeded `ledger.Account` rows:

| Code | Meaning | Dimensions |
|---|---|---|
| `CASH` | cash in drawer | shift |
| `BANK_PENDING` | transfers awaiting verification | |
| `BANK` | verified bank money | |
| `AR_PATIENT` | patient receivable | patient, invoice |
| `AR_PAYER` | payer receivable | payer, invoice |
| `PATIENT_CREDIT` | money held for patient (liability) | patient |
| `REVENUE` | service revenue | department, service kind |
| `DISCOUNT` | discounts given (contra revenue) | |
| `WRITE_OFF` | payer rejections written off | payer |
| `CASH_OVER_SHORT` | shift variances | shift |

Postings (each a balanced JournalEntry with `source_type`, `source_id`):
- Invoice approved: Dr AR_PATIENT (patient share), Dr AR_PAYER (payer share), Dr DISCOUNT (discount) / Cr REVENUE (gross).
- Payment received: Dr CASH or BANK_PENDING / Cr PATIENT_CREDIT.
- Allocation: Dr PATIENT_CREDIT / Cr AR_PATIENT.
- Transfer confirmed: Dr BANK / Cr BANK_PENDING. Rejected: reverse allocations (Dr AR_PATIENT / Cr PATIENT_CREDIT) then Dr PATIENT_CREDIT / Cr BANK_PENDING (or BANK if it was confirmed).
- Credit note: reverse the credited shares (Dr REVENUE / Cr AR_PATIENT, Cr AR_PAYER, Cr DISCOUNT). If the invoice becomes over-allocated, de-allocate the excess: Dr AR_PATIENT / Cr PATIENT_CREDIT.
- Refund: Dr PATIENT_CREDIT / Cr CASH.
- Shift variance: CASH vs CASH_OVER_SHORT.
- Payer rejection rebilled: Dr AR_PATIENT / Cr AR_PAYER. Written off: Dr WRITE_OFF / Cr AR_PAYER. Payer payment: Dr BANK / Cr AR_PAYER.

JournalEntry and JournalLine are append-only (trigger blocks UPDATE/DELETE). Inventory is tracked by StockMove, not the money ledger.

### 4.8 Stock

- StockMove is the append-only stock ledger: `(item, batch, store, qty_base_units signed, kind, source)`. On-hand = sum of moves. Kinds: receipt, dispense, adjustment, transfer_out, transfer_in, count_correction, return.
- Quantities stored in base units (e.g. tablet). UnitConversion defines box→strip→tablet factors.
- Dispense picks batches FEFO (earliest expiry, non-expired, positive on-hand) via `domain/stock.py`; pharmacist may override batch with reason.
- Stock never goes negative (domain check under `select_for_update` on batch rows).
- Stock decrements at dispense, never at invoicing.

### 4.9 Immutability and audit

- `django-pgtrigger` protections: approved Invoice/InvoiceLine, approved CreditNote, closed Shift, JournalEntry/Line, StockMove, approved ResultVersion, Allocation (reversal = new negative allocation row, never edit).
- `django-pghistory` tracks every mutable model with context (user id, request id, reason). Services set context via `pghistory.context(user=..., reason=...)`. Middleware attaches the request user.

### 4.10 Permissions

- Permission codes are strings `"<app>.<action>"` registered in `apps/core/permissions.py` with default roles. `RolePermission` rows override defaults (editable matrix).
- Roles: `receptionist`, `doctor`, `cashier`, `cashier_supervisor`, `pharmacist`, `lab_tech`, `lab_supervisor`, `nurse`, `accountant`, `manager`, `admin`. A user may hold several roles.
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
| E2E | Playwright (chromium) | Each feature's main flow at 3 viewports; overflow check for every route × 3 viewports × 3 themes × 2 languages; screenshots to `artifacts/screens/<route>-<viewport>-<theme>-<lang>.png` for (ar,light), (en,dark), (ar,warm) |

E2E seed users (one per role) are created by `manage.py seed_e2e`; credentials live in `e2e/fixtures/users.ts` and `backend/apps/core/management/commands/seed_e2e.py` only (test values, never real).

## 7. Git workflow (see `.claude/skills/ship-feature/SKILL.md`)

Branch `feat/<phase>-<slug>` → Conventional Commits → `make check` + e2e for touched areas → self-review checklist → fix → push → PR → CI green → squash merge to `main` → update `CHANGELOG.md` and `PROGRESS.md`.

## 8. Things that are never allowed

- Business logic in routers or React components.
- Floats for money. Raw SQL updates to protected tables outside migrations.
- Any runtime fetch to the internet (fonts, CDNs, analytics). The app must work on an isolated LAN.
- Raw colors, physical-direction utilities, or hardcoded strings in UI code.
- Features tagged P2 or Later before Phase 8 is complete.
- Weakening a test to make it pass. Fix the code or record an ADR explaining the rule change.
