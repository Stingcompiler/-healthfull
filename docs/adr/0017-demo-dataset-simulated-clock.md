# 0017. Demo dataset: a month of history through the services under a simulated clock

Date: 2026-10-10. Status: accepted.

## Context

Phase 8 needs a realistic demo database (PROMPT.md, "بيانات التجربة"): a center with five
departments, ten doctors, a dated SDG price list, about 200 drugs with batches and expiries,
about 50 lab tests, three payers with different rules, 500 Sudanese patients and a month of
visits, invoices and shifts. The month must hold together the way real data does: frozen
invoices priced from the list effective on their day, closed shifts with frozen reports, a
ledger that balances, stock that never went negative, results approved by a supervisor.

Writing those rows directly would bypass the services and the database guards, and would
produce data the application itself could never have made. But the services stamp every
row with the current time, and several rules depend on "today" (price versions start
tomorrow at the earliest, a shift opens now, a batch is usable through its expiry).

## Decision

1. `manage.py seed_demo` builds the configuration and then plays the month day by day
   through the services only, as the user each screen would act as (`apps/core/demo/`).
   Configuration with no service (center profile, users, departments, rooms, doctor
   profiles and schedules, stores, suppliers, tills) is written the way `seed_e2e` writes it.
2. Time is simulated: while the past is played, `django.utils.timezone.now` is replaced by a
   `DemoClock` (`apps/core/demo/clock.py`). `localdate()` and `auto_now` fields read it too,
   so every rule judges each step on its own day. The clock never goes backwards and ticks
   one millisecond per reading, so rows keep their order. Today's activity stops two minutes
   before the real time; today's shifts, queue and work lists stay open for the demo.
3. Database-side times are not simulated: `pghistory` audit rows and
   `StockBalance.updated_at` (PostgreSQL `now()`) show when the seed ran. The audit viewer
   therefore shows the seed time for demo history; that is acceptable for demo data.
4. Deterministic: one seeded `random.Random` drives every choice (people, visits,
   scenarios, payments, variances). The same seed and volumes give the same past days for a
   run on the same date (today's partial day depends on the time of the run). Idempotent:
   configuration parts are created only when missing; the activity is made only when the
   database has no visit yet. Existing accounts keep their password (a run on an e2e
   database never changes the e2e accounts).
5. Guard: the command writes accounts with a known demo password, so it refuses any database
   not named `demo_*`, `e2e_*` or `test_*`. `make demo` only creates and drops `demo_*`.
6. Transactions: the configuration is one transaction and each played day is one more (the
   deferred journal balance trigger checks every entry at each day's commit). One
   transaction for the whole month kept every superseded row version alive (sequence rows,
   service lines and stock balances are updated at every step) and each lookup walked those
   chains, so the run slowed down day after day. The last write is the cash price version
   for the 1st of next month (note `COMPLETE_MARK`); a database with visits but without it
   holds an interrupted run, and the command says to start again with `DEMO_RESET=1`.
7. Audit context: each simulated event opens its own `pghistory.context(command="seed_demo",
   event=...)`. A single context around the whole run made every audited write rewrite the
   same `pghistory_context` row (its metadata changes with each service's user and reason),
   which was the other half of the slowdown.

## Consequences

- Every invariant and database guard holds for the demo data, which doubles as a long
  integration test of the services (`apps/core/tests/test_seed_demo.py` plays a small month
  and checks the ledger, shifts, invariants 1 and 5, and idempotency).
- A full run issues roughly 500 queries per visit (the services' own work); the default
  month (30 visits on a working day, about 800 visits) takes several minutes. `--days`,
  `--patients` and `--visits-per-day` make smaller sets.
- New services that read the time some other way (`date.today()`, `datetime.now()`, a model
  `default=timezone.now` bound at import) would escape the simulated clock; keep using
  `timezone.now()` / `timezone.localdate()`.
