# End-to-end tests

Playwright specs against the real backend (Django) and frontend (Vite), on a throwaway
PostgreSQL database per checkout (`e2e_hospital_<hash>`, ARCHITECTURE 3 and 6).

```
make e2e                          # drop + migrate + seed the e2e DB, start both servers, run every spec
make e2e E2E_GREP=@helpers        # only tests whose title matches
cd e2e && pnpm exec playwright test tests/helpers.spec.ts   # reuse the existing e2e DB (no reset)
```

| Path | What |
|---|---|
| `env.ts` | repo paths, worktree hash, ports, `DB_NAME` (from `E2E_DB_NAME`), `BASE_URL` |
| `global-setup.ts` | warms Vite, saves the admin and pharmacist sessions to `.auth/` |
| `fixtures/users.ts` | seed users and the test password (`USERS`, `EXTRA_DOCTORS`, `resolveUser`) |
| `fixtures/state.ts` | saved browser sessions (`ADMIN_STATE`, `PHARMACIST_STATE`, `ANONYMOUS_STATE`) |
| `helpers/` | login, preferences, layout, screenshots, i18n, `reseed()`, and **`api.ts`** (below) |
| `helpers/adapters/` | per-module API adapters for the factories (below) |
| `routes.ts`, `route-kit.ts` | the route registry for the responsive matrix: module roots here, plus every `module-routes/<module>.ts` |
| `module-routes/` | one file per module listing the screens it adds (`export const routes`) |
| `tests/` | the specs; one worker, so specs share the database in file order |

Specs import everything from `../helpers`.

## Seed data (`manage.py seed_e2e`)

`scripts/e2e.sh` runs the seed before Playwright, and `reseed()` runs it again (it is
idempotent: users and configuration go back to the seed values; price versions and stock
receipts are never created twice). Source: `backend/apps/core/management/commands/seed_e2e.py`
and `backend/apps/core/e2e/catalog.py`.

### Users

All use the test password `E2E_PASSWORD` (`fixtures/users.ts`).

| Username | Role | Notes |
|---|---|---|
| `reception`, `doctor`, `cashier`, `cashsup`, `pharmacist`, `labtech`, `labsup`, `nurse`, `accountant`, `manager`, `admin` | one role each (`USERS`) | `doctor` is the general practitioner (GEN) |
| `pediatrician`, `gynecologist`, `dentist` | doctor (`EXTRA_DOCTORS`) | PED, GYN, DEN clinics |
| `root` | superuser, no role | break-glass account only |

### Catalog

| What | Codes |
|---|---|
| Departments | `GEN`, `PED`, `GYN`, `DEN`, `LAB`, `PHA`, `PRC` (procedures and nursing), `ER`, `WRD` (inpatient ward) |
| Rooms | `GEN-1`, `GEN-2`, `PED-1`, `GYN-1`, `DEN-1`, `LAB-1`, `PRC-1`, `ER-1`; wards `WRD-M`, `WRD-F`, `WRD-P` |
| Beds | `M-01`..`M-04`, `F-01`..`F-04` (`F-04` out of service), `P-01` (private room) |
| Doctor schedules | `doctor`: Sat-Thu 08:00-14:00 and Fri 16:00-20:00 (every day has slots); `pediatrician`: Sun/Tue/Thu 09:00-13:00, Sat 17:00-21:00; `gynecologist`: Sat/Mon/Wed 10:00-14:00; `dentist`: Sun-Thu 16:00-20:00 |
| Tills, banks | `T1`, `T2`; banks `BOK` (Bankak), `FIB`, `ONB`, `OTHER` |
| Reason codes | every default of `backend/apps/core/reason_codes.py`, active |

Services (cash price in SDG, per base unit for drugs and consumables):

| Kind | Code: price |
|---|---|
| consultation | `CONS-GEN` 15,000 · `CONS-PED` 20,000 · `CONS-GYN` 25,000 · `CONS-DEN` 15,000 · `CONS-ER` 20,000 |
| lab | `LAB-CBC` 12,000 · `LAB-BFMP` 5,000 (malaria) · `LAB-FBS` 4,000 · `LAB-RBS` 3,500 · `LAB-RFT` 9,000 · `LAB-UA` 5,000 |
| procedure | `PRC-INJ` 2,000 · `PRC-CANNULA` 3,000 · `PRC-DRESS` 5,000 · `PRC-SUTURE` 15,000 · `PRC-NEB` 4,000 · `PRC-ECG` 10,000 · `GYN-US` 20,000 · `DEN-EXT` 25,000 · `DEN-FILL` 30,000 |
| drug | `DRG-PARA500` 50 · `DRG-AMOX500` 300 · `DRG-IBU400` 100 · `DRG-COART` 500 · `DRG-METRO500` 150 · `DRG-CEFTRI1G` 3,500 · `DRG-PARASYR` 1,500 · `DRG-ORS` 300 |
| consumable | `CNS-SYR5` 200 · `CNS-CANNULA20` 1,500 · `CNS-GAUZE` 500 · `CNS-GLOVES` 300 |
| bed | `BED-WARD` 30,000 · `BED-PRIV` 60,000 |

A visit with a doctor creates that doctor's consultation line (`CONS-GEN` for `doctor`, ...). A
second visit with the same doctor within 7 days is a free follow-up (no fee line).

Price lists and payers. Every list has a version effective from the day of the seed; `CASH` also
has a +10% version starting on the 1st of next month (today's prices are unchanged).

| Payer | Price list | Rule | Example: `CONS-GEN` (payer / patient) |
|---|---|---|---|
| (cash) | `CASH` | patient pays all | 0 / 15,000 |
| `AMAN` insurance | `AMAN` = cash x 0.90 | payer pays 70%; `GYN-US` needs a pre-approval reference; `DEN-FILL` excluded (100% patient) | 9,450 / 4,050 |
| `NAKHEEL` company | `NAKHEEL` = cash | patient copay 2,000 per line | 13,000 / 2,000 |
| `RAHMA` charity | `RAHMA` = cash x 0.80 | payer pays up to 10,000 per line; no card number needed | 10,000 / 2,000 |

Pharmacy: stores `MAIN` (main store) and `PHA` (outpatient pharmacy, dispenses). Every drug and
consumable has a stock item with its units (e.g. paracetamol: tablet, strip = 10, box = 100) and
two batches with different expiries (relative to the seed day), received into `PHA` (both) and
`MAIN` (the later one). Amoxicillin and ORS have a batch expiring within 30 days; ceftriaxone
(8 vials, minimum 20) is the low-stock item. Drug classes for allergy alerts: `PENICILLIN`
(amoxicillin), `CEPHALOSPORIN` (ceftriaxone), `NSAID` (ibuprofen).

Lab tests (`LabTest.code`): `CBC` (WBC, HGB by sex and age, PLT), `BFMP` (malaria, positive or
negative), `FBS` and `RBS` (glucose), `RFT` (urea, creatinine by sex), `UA` (colour, pH, protein
and glucose grades, pus cells), with normal and critical limits.

`await seededCatalog()` returns the ids of all of this by code (`fixture("catalog")`).

## API clients

```ts
import { apiAs, ApiError, newApiClient, disposeApiClients } from "../helpers";

const cashier = await apiAs("cashier");             // logged in, shared per user per worker
const me = await cashier.get<{ roles: string[] }>("/api/auth/me");
await cashier.post("/api/payments/...", { amount: "15000.00" });   // X-CSRFToken added
await cashier.call("auth_update_preferences", { body: { theme: "dark" } }); // by OpenAPI operation id
test.afterAll(disposeApiClients);
```

- `apiAs(who)` takes a user key (`"cashsup"`), an extra doctor (`"pediatrician"`) or a role code
  (`"cashier_supervisor"`). `newApiClient(who)` gives a private client (dispose it yourself).
- Every unsafe request carries the current `csrftoken` cookie as `X-CSRFToken` (Django rotates it
  at login). A request that gets 401 signs in again once (after `reseed()` or a password change).
- A non-2xx answer throws `ApiError` with `status`, `code` and `details` from the backend's
  `{code, message, details}`; pass `{ expect: 409 }` to read an error body instead.
- `call(operationId, { path, query, body })` takes method and path from `frontend/openapi.json`
  and refuses body fields the operation does not declare.

## Fixtures: `manage.py e2e_fixture`

Data a spec needs before its screen is built through the services, never by writing rows. Each
fixture acts as a seed user (`as`, defaulting to the role that does the step), checks the
permission the matching endpoint will require, and runs in one transaction: a refused step
leaves nothing behind.

```ts
import { fixture, FixtureError } from "../helpers";
const { shift } = await fixture<{ shift: ShiftRef }>("open_shift", { opening_float: "5000" });
```

```
cd backend && DB_NAME=e2e_hospital_<hash> DJANGO_DEBUG=1 uv run python manage.py e2e_fixture --list
... e2e_fixture patient --params '{"payer": "AMAN"}' --json
```

Output is `{"ok": true, "result": ...}`; a refusal prints `{"ok": false, "error": {code, message,
details}}` and exits 2, and the helper throws `FixtureError` with that `code` (for example
`SHIFT_ALREADY_OPEN`, `PREAPPROVAL_REQUIRED`, `PERMISSION_DENIED`). References are ids or
numbers (`"PT-2026-000012"`, `"VIS-..."`, `"INV-..."`, `"SH-..."`), codes for catalog rows, and
usernames for users. Money is a string (`"15000.00"`) or a whole number, never a float. Unknown
parameters are refused. The command runs only on `e2e_*` / `test_*` databases with DEBUG on.

| Fixture | Acts as | Does |
|---|---|---|
| `catalog` | | ids of the seeded catalog by code |
| `patient` | reception | registers a patient (generated Sudanese name and phone unless given; duplicate check skipped unless `confirm_not_duplicate: false`; `emergency: true` for name-and-sex registration); with `payer`, adds that coverage; `allergies` (drug class codes such as `PENICILLIN`, or `{substance, allergen_type}`) are recorded by `allergies_as` (default `nurse`) |
| `coverage` | reception | puts a payer's coverage on a file |
| `visit` | reception | opens a visit: `doctor` (default `doctor`, `null` for none), `department`, `visit_type`, `coverage` (`default`, `cash` or a payer code on file); returns lines and the queue entry |
| `order` | doctor | orders `items` (`{service, quantity?, note?, pre_approval_ref?, prescription?}`) after the allergy check; a prescription with `dose_quantity`, `frequency_per_day`, `duration_days` sets the quantity |
| `invoice` | cashier | drafts an invoice from unbilled lines (all, `lines` ids or `services` codes); `approve: true` approves |
| `approve_invoice` | cashier | approves a draft `invoice`, or drafts and approves a `visit`'s unbilled lines |
| `open_shift` | cashier | opens a shift (`opening_float`, `till`); `if_open`: `error`, `reuse` or `close` |
| `pay` | cashier | takes a payment for an `invoice`, a `visit` or a `patient`: `amount` (default: what is owed), `method` (`cash`, `bank_transfer`, `qr`, `card`, `patient_credit`), `bank` (default `BOK`), `reference` (default unique), `allocate: "none"` for credit; opens a zero-float shift when none is open |
| `close_shift` | cashier | closes the open shift at the expected cash, or at `counted` with a variance `reason` |
| `paid_visit` | reception, then cashier | patient (`patient` or new from `patient_fields`) + visit + consultation invoiced and paid in cash: the visit waits ready in the doctor's queue (the cashier's shift stays open) |

A module can add fixtures without touching shared files: create `backend/apps/<app>/e2e_fixtures.py`
that registers builders with `apps.core.e2e.fixtures.fixture` (the command imports every app's
`e2e_fixtures` module), then call `fixture("<name>", params)` from a spec.

## Factories

Typed wrappers over the fixtures, in `helpers/api.ts`:

| Factory | Returns |
|---|---|
| `createPatient(options?)` | `{ patient, coverage, allergies }` |
| `addCoverage({ patient, payer, ... })` | `CoverageRef` |
| `createVisit({ patient, doctor?, coverage?, ... })` | `{ visit, lines, queue_entry }` |
| `orderLines({ visit, items, as? })` | `ServiceLineRef[]` |
| `createInvoice({ visit, lines?, services?, approve? })` | `{ invoice, lines }` |
| `approveInvoice({ invoice } \| { visit, lines?, services? })` | `{ invoice, lines }` |
| `pay({ invoice \| visit \| patient, amount?, method?, ... })` | `{ payment, allocations, invoices, lines, shift }` |
| `openShift({ opening_float?, till?, if_open? })` | `ShiftRef` |
| `closeShift({ shift?, counted?, reason?, note? })` | `ShiftRef` |
| `paidVisit({ doctor?, patient?, patient_fields?, ... })` | everything above for one visit |
| `seededCatalog()` | `CatalogRef` (cached) |

Rows can be passed as the result objects, ids, or numbers. Results are snake_case like the API,
with money as strings.

```ts
const { patient } = await createPatient({ payer: "AMAN" });
const { visit } = await createVisit({ patient });
await orderLines({ visit, items: [{ service: "LAB-CBC" }, { service: "DRG-AMOX500", quantity: 21 }] });
const { invoice } = await approveInvoice({ visit });      // AMAN: 70% payer, 30% patient
await openShift({ opening_float: "5000", if_open: "close" });
const paid = await pay({ invoice });                      // lines are now "paid"
await closeShift({ counted: "4000", reason: "COUNTING_ERROR" });
const ready = await paidVisit({ doctor: "pediatrician" }); // waits in the pediatric queue
```

### Through the real API: adapters

A factory calls the real API instead of the fixture once an adapter for it is registered and
every operation the adapter lists is in `frontend/openapi.json`. When your module ships such an
endpoint, copy `helpers/adapters/_template.ts` to `helpers/adapters/<module>.ts` (files starting
with `_` are skipped), list your operation ids and map the response to the factory's result.
Every spec then goes through your endpoint, with no edit to shared files. An adapter may return
`undefined` (before calling anything) for options its endpoint does not cover; the fixture takes
over.

`E2E_FACTORY_MODE`: `auto` (default), `fixture` (never use adapters), `api` (fail when a factory
has no usable adapter: `E2E_FACTORY_MODE=api make e2e E2E_GREP=@cashier` proves your endpoints).

## Conventions

- One worker and one database: specs see each other's data. Create what you need (unique
  patients per test), search by file number, and leave shared state clean (close the cashier's
  shift, `reseed()` after changing a seed user).
- A fixture call starts a Django process (about two seconds): prefer `paidVisit` and the
  `visit`-level options to many small calls, and raise the test timeout for long set-ups
  (`test.describe.configure({ timeout: 120_000 })`).
- Tag specs with their module (`@patients`, `@clinic`, `@cashier`, `@admin`) for `E2E_GREP`.
- New screens go into your module's `module-routes/<module>.ts` (never `routes.ts`); the
  responsive matrix then checks each at 3 viewports x 3 themes x 2 languages, and the route
  registry test fails until every `path` your `routes.tsx` declares is listed. A screen with
  path parameters gets `resolve`, which builds its data once per worker and returns the path:

  ```ts
  import { createPatient } from "../helpers";
  import { appRoute, type AppRoute } from "../route-kit";

  export const routes: readonly AppRoute[] = [
    appRoute("patient-file", "/patients/$patientId", {
      resolve: async () => `/patients/${String((await createPatient()).patient.id)}`,
    }),
  ];
  ```
