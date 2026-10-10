# hospital-sys

A medical center management system for outpatient clinics and small hospitals in Sudan. It runs
on one mini PC on the clinic's local network and needs no internet: reception, doctors, the
cashier, pharmacy, laboratory, nursing, insurance claims, reports and a patient portal, in Arabic
(right to left) and English, on desktops, tablets and phones.

نظام لإدارة المراكز الطبية في السودان، يعمل على شبكة المركز المحلية دون إنترنت، بالعربية
والإنجليزية: الاستقبال، الطبيب، الخزينة، الصيدلية، المعمل، التمريض، مطالبات التأمين، التقارير،
وبوابة المريض. أدلة المستخدمين بالعربية في [docs/guides/](docs/guides/README.md).

The business cycle it enforces: **register, see the doctor, order, invoice, pay, then perform**
(a service is given only after its line is invoiced and settled, or under a documented
perform-first authorization). Seven invariants guard the money and the stock; they are listed
in [CLAUDE.md](CLAUDE.md) and explained in [docs/FLOW.md](docs/FLOW.md).

## Documentation

| Read | For |
|---|---|
| [docs/guides/](docs/guides/README.md) | user guides per role (Arabic, with English summaries) and a patient portal guide |
| [docs/runbooks/](docs/runbooks/README.md) | install, daily operations, backup and restore, update and rollback, troubleshooting |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | layout, layering, money, ledger, states, API and UI conventions (binding for contributors) |
| [docs/FLOW.md](docs/FLOW.md) | the business cycle and the seven invariants |
| [docs/FEATURES.md](docs/FEATURES.md) | every feature by number and phase tag |
| [docs/DECISION.md](docs/DECISION.md), [docs/STACK.md](docs/STACK.md), [docs/adr/](docs/adr/) | product decisions, stack rationale, architecture decision records |
| [PROGRESS.md](PROGRESS.md), [CHANGELOG.md](CHANGELOG.md) | build status, follow-ups, release notes |

## Architecture overview

```
 browsers on the LAN (desktop, tablet, phone)        patients' phones on the clinic Wi-Fi
            |                                                   |
            v                                                   v
   web (Caddy: SPA + /api proxy, optional internal TLS)  ---->  /portal/* (same SPA)
            |
            v
   app (gunicorn, Django 5.2 + django-ninja)  --- connects as hospital_app (rows only)
            |
            v
   db (PostgreSQL 16)  <--- migrate (one-off, hospital_owner)   backup sidecar (superuser):
            ^                                                    nightly pg_dump, restore tests,
            +--- maintenance loop (sessions, alerts, bed nights)   optional pgBackRest WAL
```

- **Backend** (`backend/`): Django 5.2 LTS, django-ninja, Python 3.12, uv. Business rules live in
  `backend/domain/` (pure Python, Hypothesis property tests) and `apps/<module>/services.py`;
  routers only check permissions and call one service. Money is `Decimal` (SDG, 2 places), never
  float. Every money event posts a balanced entry to an append-only double-entry ledger.
- **Database guards**: PostgreSQL triggers make approved invoices, credit notes, closed shifts,
  the ledger, allocations, stock moves and approved lab results immutable; a stock balance can
  never go below zero; `django-pghistory` audits every mutable row with user and reason.
- **Frontend** (`frontend/`): React 19, Vite, TypeScript strict, Tailwind v4 with semantic design
  tokens (light, dark, warm themes), i18next with Arabic and English in key parity, logical
  (RTL-safe) layout, a typed API client generated from the committed OpenAPI file.
- **Patient portal** (`frontend/src/portal`, `/api/portal`): the same SPA, its own session and
  sign-in (file number, phone, receipt code), own-data endpoints only.
- **Infrastructure** (`infra/`): Docker images and compose, Caddy, backup and restore scripts,
  `update.sh` with automatic rollback, database role setup; a local device agent (`agent/`) for
  receipt and label printers.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start for developers

Prerequisites: macOS or Linux, PostgreSQL 16 on the local socket (Homebrew `postgresql@16`), uv,
Node 24 with pnpm, GNU Make.

```bash
make setup      # uv sync, pnpm install (frontend, e2e), Playwright chromium, create dev DB, migrate
make seed       # demo data into the dev DB (seed_demo when present, else seed_e2e: users, catalog)
make dev        # backend + frontend on this worktree's ports (make ports prints them)
make check      # lint + typecheck + backend and frontend tests + OpenAPI drift; green before any merge
make e2e        # fresh e2e DB, seed, both servers, Playwright (E2E_GREP=@cashier to filter)
make infra-test # shell lint, update.sh, roles, backup/restore and restore-drill tests
make help       # every target
```

`make demo` (a separate demo database with a month of simulated activity through the services)
arrives with the demo-data work of phase 8 (`seed_demo`, `docs/runbooks/demo.md`). Several
checkouts can run side by side: database names and ports derive from the worktree path
(`DB_NAME`, `TEST_DB_NAME`, `BACKEND_PORT`, `FRONTEND_PORT` override them; ARCHITECTURE section 3).
E2E sign-in users and their test passwords are in `e2e/fixtures/users.ts`.

Contributors and coding agents follow [CLAUDE.md](CLAUDE.md) and the `ship-feature` skill in
`.claude/skills/`.

## Deployment summary

One mini PC (4+ cores, 8-16 GB RAM, SSD, second disk for backups) behind a UPS, Ubuntu Server
24.04, Docker with the compose plugin. Everything after the images are on the machine works
offline.

1. Install: [docs/runbooks/install.md](docs/runbooks/install.md) (hardware and UPS, OS and
   firewall, `.env`, database roles, first start, first admin, backup proof, UPS shutdown).
2. Operate: [docs/runbooks/operations.md](docs/runbooks/operations.md) (daily checks, users,
   power and internet failures, dead server, `manage.py integrity_check`, troubleshooting).
3. Back up and restore: [docs/runbooks/backup-restore.md](docs/runbooks/backup-restore.md)
   (nightly verified dumps, monthly restore tests, the restore-from-scratch drill, off-site USB,
   new server after a disaster, optional pgBackRest point-in-time recovery).
4. Update: [docs/runbooks/update-rollback.md](docs/runbooks/update-rollback.md)
   (`infra/update.sh --tag <release>`: backup, migrations as the owner role, swap, health check,
   automatic rollback, every run recorded in the update history).

## Feature map

Feature numbers refer to [docs/FEATURES.md](docs/FEATURES.md); status per item in
[PROGRESS.md](PROGRESS.md).

| Module | Screens (route) | FEATURES |
|---|---|---|
| Platform | sign-in, forced password change, app shell, search, bell, prints, status page | 0.1-0.11, 0.13 |
| Patients and registration (`patients`) | `/patients`, `/patients/new`, `/patients/$patientId`, `/patients/import`, portal codes | 1.1-1.6, 1.8 |
| Visits and queue (`visits`) | `/queue`, `/appointments`, waiting-room kiosk `/display/queue` | 2.1-2.7 |
| Doctor (`clinic`) | `/clinic`, `/clinic/visits/$visitId` | 3.1-3.9, 4.1, 4.2 |
| Orders and work lists (`orders`) | service-line states, perform-first, exception reports | 4.1-4.5 |
| Billing and coverage (`billing`, `catalog`) | cashier desk invoices, credit notes, price lists, payers | 5.2-5.6, 5.8-5.12 |
| Payments and cashier (`payments`) | `/cashier`, receipts, transfers, refunds | 6.1-6.9 |
| Shifts and cash control (`payments`) | `/cashier/shift`, handovers, close, review | 7.1-7.6 |
| Pharmacy and stock (`pharmacy`) | `/pharmacy/*`: dispense, walk-in sale, items, receipts, adjustments, counts, transfers, expiry, low stock, returns | 8.1-8.10, 8.13 |
| Laboratory (`lab`) | `/lab/*`: work list, samples, labels, results, approval, catalog, turnaround | 9.1-9.8 |
| Procedures and nursing (`nursing`) | `/nursing`, `/nursing/visits`, `/nursing/beds` | 3.4, 10.1-10.3, 10.5 |
| Insurance claims (`claims`) | `/claims/*`: receivables, batches, claim build and answers, payer payments, aging | 11.1-11.7 |
| Reports and dashboard (`reports`) | `/` (manager dashboard), `/reports`, `/reports/$reportKey` | 4.5, 12.1-12.11 |
| Administration (`core`, `imports`, `ops`) | `/administration/*`: users, roles, catalog, price lists, payers, settings, imports, system status, export, audit | 0.2, 0.3, 1.8, 8.13, 13.1-13.3, 13.8-13.10 |
| Data protection and operations (`ops`, `infra/`) | backups, restore tests and drill, integrity check, update history, roles | 14.1-14.6 |
| Patient portal (`portal`) | `/portal/*`, receipt check `/verify/$token` | 9.4, 15.1, 15.2 |

## Screenshots

`make e2e` saves a screenshot of every screen at three widths, in three themes and two languages
to `artifacts/screens/<route>-<viewport>-<theme>-<lang>.png` (not committed), for the
combinations (ar, light), (en, dark) and (ar, warm); for example
`artifacts/screens/cashier-375x812-light-ar.png`. Viewports: `375x812`, `768x1024`, `1280x800`.
Route names (from `e2e/routes.ts` and `e2e/module-routes/*.ts`):

- Shell and platform: `login`, `change-password`, `dashboard`, `not-found`, `design`
- Patients and visits: `patients`, `patient-new`, `patient-import`, `patient-file`,
  `patient-portal-code`, `queue`, `queue-display`, `appointments`
- Doctor: `clinic`, `clinic-visit`
- Cashier: `cashier`, `cashier-desk-visit`, `cashier-desk-transfer`, `cashier-shift`,
  `cashier-shift-report`, `cashier-shift-signoff`, `cashier-review`, `cashier-transfers`,
  `cashier-credit-notes`, `cashier-refunds`, `cashier-perform-first`, `cashier-receipt`,
  `cashier-receipt-check`, `cashier-invoice-print`
- Pharmacy: `pharmacy`, `pharmacy-queue`, `pharmacy-sale`, `pharmacy-items`, `pharmacy-item`,
  `pharmacy-receipts`, `pharmacy-adjustments`, `pharmacy-counts`, `pharmacy-count`,
  `pharmacy-transfers`, `pharmacy-expiry`, `pharmacy-low-stock`, `pharmacy-returns`
- Laboratory: `lab`, `lab-result-entry`, `lab-result-amended`, `lab-result-print`, `lab-label`,
  `lab-approve`, `lab-catalog`, `lab-catalog-test`, `lab-tat`
- Nursing: `nursing`, `nursing-desk`, `nursing-visits`, `nursing-chart`, `nursing-beds`
- Claims: `claims`, `claims-receivables`, `claims-batches`, `claims-build`, `claims-detail`,
  `claims-detail-draft`, `claims-print`, `claims-payments`, `claims-aging`
- Reports: `reports`, `reports-revenue`, `reports-paid-not-performed`, `reports-print`
- Administration: `administration`, `admin-users`, `admin-roles`, `admin-catalog`,
  `admin-price-lists`, `admin-price-list`, `admin-payers`, `admin-payer`, `admin-settings`,
  `admin-policies`, `admin-departments`, `admin-reason-codes`, `admin-imports`, `admin-system`,
  `admin-export`, `admin-audit`
- Patient portal: `portal`, `portal-home`, `portal-appointments`, `portal-book`,
  `portal-results`, `portal-result`, `portal-prescriptions`, `portal-invoices`,
  `portal-invoice`, `portal-receipt`, `portal-verify`

(`patient-portal-code` and `pharmacy-returns` come with the phase 8 follow-ups.)

## Security model

- **Roles and permissions.** Twelve roles: receptionist, doctor, cashier, cashier supervisor,
  pharmacist, lab technician, lab supervisor, nurse, accountant, manager, system admin, and
  `display` (the waiting-room kiosk, which can only read the queue display). Every endpoint
  checks a permission code (`<app>.<action>`, `@require_perm`); defaults per role are in code,
  and an admin edits the matrix with a reason. Doctors hold no billing permission and never see
  prices. The frontend hides what you cannot do, but the server decides.
- **Sign-in.** Session cookie with CSRF; 5 wrong passwords lock an account for 15 minutes
  (unknown usernames lock the same way), per-address throttling, forced password change after
  an admin reset, idle timeout; every sign-in, failure and unlock is in the audit trail (ADR 0004,
  0005).
- **Separation of duties.** Second-person checks: transfer confirmation, credit note approval,
  refunds, shift review, and (with the phase 8 follow-ups) paid dispense returns, admissions
  cancelled in error, claim rebills and write-offs (ADR 0008, 0018). Discounts beyond a role's
  limit need a supervisor's credentials.
- **Audit.** `django-pghistory` records every change to mutable rows in the database (who, when,
  before, after, reason), and cancellations, discounts, refunds, overrides and confirmations store
  reason, approver and time on the row (invariant 4). Admins browse it at `/administration/audit`.
- **Immutability triggers.** PostgreSQL triggers refuse changes to approved invoices and credit
  notes, closed shifts, the journal, allocations, stock moves, dispenses, approved lab results and
  frozen price versions, and refuse `TRUNCATE` on 22 money and stock tables; the deferred balance
  trigger refuses an unbalanced journal entry. `manage.py integrity_check` re-verifies the books
  and the stock at any time.
- **Non-owner database role.** The application connects as `hospital_app`, which can read and
  write rows but owns nothing: it cannot `TRUNCATE`, `ALTER`, drop tables or disable triggers.
  Migrations run as `hospital_owner` through a one-off container; only the db and backup
  containers use the superuser (ADR 0006 (m), `infra/db/`).
- **Portal separation.** The patient portal has its own session cookie (path `/api/portal`, hashed
  token, short idle and absolute limits), its own sign-in with hashed receipt codes and lockouts,
  and endpoints that only ever return the signed-in patient's own rows (anyone else's is a 404).
  Staff sessions never reach portal data and portal sessions never reach staff endpoints
  (ADR 0016).
- **Network.** LAN only, no runtime internet dependency (fonts and libraries are bundled), the web
  container bound to the LAN address, optional internal TLS with a clinic root certificate.
- **Backups.** Verified nightly dumps with checksums, monthly restore tests, a restore drill, and
  encrypted pgBackRest repositories when enabled.

## License

To be decided by the owner before distribution. Until a license file is added, all rights are
reserved.
