# Demo database — قاعدة البيانات التجريبية

A ready demo center for training, user tests and presentations: one month of realistic
activity ending today, made through the application's own services (ADR 0017). Never load it
into a database that holds real patients; the command refuses any database not named
`demo_*` (or `e2e_*` / `test_*` for tests).
Related: [install.md](install.md).

## 1. Make it — الإنشاء

On a development machine (PostgreSQL 16 running, `make setup` done):

```bash
make demo                         # creates demo_hospital if missing, migrates, seeds
make demo DEMO_RESET=1            # drop it first: a fresh month that ends today
DB_NAME=demo_hospital make dev    # run the app on it
```

Options: `DEMO_DB_NAME=demo_<name>` picks another database, and `DEMO_ARGS` passes options to
`manage.py seed_demo`:

| Option | Default | Meaning |
|---|---|---|
| `--seed` | 2026 | random seed: the same seed, options and day give the same data |
| `--days` | 30 | days of history before today (1-120) |
| `--patients` | 500 | synthetic patients |
| `--visits-per-day` | 42 | visits on a working day (Fridays about a quarter) |

The default month takes several minutes (about 500 database queries per visit, all through
the services); `DEMO_ARGS="--days 7 --visits-per-day 15"` makes a small set in about a minute.
Running it again on the same database adds nothing: the configuration is completed if parts
are missing, and the activity is made only when the database has no visit yet. To refresh the
month, use `DEMO_RESET=1`.

On a demo server running the Docker stack, set `DB_NAME=demo_hospital` in `.env` before the
first `up`, then run the seed once through the app image's `manage` entrypoint (not run in
Docker on the build machine yet; no Docker there):

```bash
infra/compose.sh run --rm --no-deps -T migrate manage seed_demo
```

## 2. Sign in — الدخول

Every demo account uses the password **`Demo-Pass-2026`** (a demo value, written in
`backend/apps/core/demo/catalog.py`; change it on any machine others can reach).

| Username | Role |
|---|---|
| `reception` | reception |
| `cashier` (morning, till T1), `cashier2` (evening, till T2) | cashier |
| `cashsup` | cashier supervisor |
| `pharmacist`, `labtech`, `labsup`, `nurse` | departments |
| `accountant`, `manager`, `admin` | back office |
| `dr.hamid`, `dr.alnour` (general), `dr.kabbashi`, `dr.suliman` (internal), `dr.alzain`, `dr.fadul` (pediatrics), `dr.awad`, `dr.gasim` (gynecology), `dr.idris`, `dr.osman` (dental) | doctors |

## 3. What is inside — المحتوى

Configuration (`backend/apps/core/demo/data.py`):

- Center "مركز الشفاء الطبي التخصصي (بيانات تجريبية)", five clinical departments (general
  medicine, internal medicine, pediatrics, obstetrics and gynecology, dental) and four service
  units (laboratory, pharmacy, procedures and nursing, inpatient ward with 9 beds).
- Ten doctors with weekly schedules (Saturday to Thursday, an evening GP on Friday) and
  consultation fees.
- SDG cash price list effective from the first day of the month, a consultation price review
  from the middle of the month, and a +10% version waiting for the 1st of next month. Payers'
  contract lists: WAHA (90% of cash), SALAM (100%), AMAL (85%).
- Three payers with different rules: WAHA insurance pays 75% (medicines 60%, obstetric
  ultrasound needs a pre-approval, three dental services excluded), SALAM company leaves a
  3,000 copay per line, AMAL charity pays up to 15,000 per line with no card number.
- 219 drugs and 14 consumables with unit packs, two batches each (a few expired during the
  month, a few expiring soon, a few below minimum stock), received into the pharmacy and the
  main store; 50 lab tests with parameters and reference ranges by sex and age.
- 500 synthetic patients with Sudanese four-part names in Arabic and English, phones,
  addresses, ages skewed young; about a third insured; some with drug allergies.

Activity (`backend/apps/core/demo/activity.py`), played day by day under a simulated clock:

- Visits with consultation fees, doctors' notes, ICD-10 diagnoses and orders drawn from common
  scenarios per clinic (malaria, typhoid, pneumonia, gastroenteritis, hypertension, diabetes,
  antenatal care, dental caries...), follow-ups, booked appointments and no-shows.
- Invoices with insurance splits and a few discounts, cash and bank-transfer payments: most
  transfers confirmed by the accountant, a few rejected (some after the shift closed, booked in
  the supervisor's till) and paid again in cash, the last two days still pending.
- Credit notes with refunds, lab tests that could not be done, approved lab results (with
  abnormal and critical values), procedures, FEFO dispenses, a stock transfer, an adjustment and
  a mid-month goods receipt, a few admissions with bed nights.
- Two shifts a day, closed with the counted cash (some variances with reasons) and signed off
  by the manager (the last two days not yet).
- Claims: WAHA's first half-month submitted, answered (some lines partly or fully rejected,
  rebilled or written off) and paid; SALAM's submitted and waiting; AMAL's still a draft; the
  rest accrued.
- Today: the cashiers' shifts, queues, lab and pharmacy work lists stay open, as at a working
  center.

Audit trail rows of the demo history carry the time the seed ran (database time), not the
simulated day.
