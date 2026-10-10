"""``manage.py seed_demo``: the demo dataset (docs/runbooks/demo.md, ADR 0017).

A medical center with five clinical departments, ten doctors with weekly schedules, a dated
SDG cash price list and three payers' contract lists, about 200 drugs with batches and
expiries, about 50 lab tests with reference ranges, three payers with different coverage
rules, 500 synthetic patients with Sudanese Arabic names and English transliterations, and
about one month of activity made only through the services under a simulated clock: visits,
orders, invoices with insurance splits, cash and transfer payments (pending, confirmed,
rejected), refunds and credit notes, dispenses, approved lab results, procedures, a few
admissions, closed and reviewed shifts with some variances, and claims at various stages.

    manage.py seed_demo                      # 30 days, 500 patients, seed 2026
    manage.py seed_demo --days 7 --patients 80 --visits-per-day 12 --seed 7

Deterministic: the same seed, volumes and day of the run give the same data. Idempotent: the
configuration is completed when parts are missing, and the activity is made only when the
database has no visit yet (a second run reports what is there and changes nothing).

Writes test accounts with a known password, so it runs only on databases named ``demo_*``,
``e2e_*`` or ``test_*``.
"""

from __future__ import annotations

import random
import re
import time as clock_time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pghistory
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.utils import timezone

from apps.core.demo.activity import Simulation, Summary
from apps.core.demo.catalog import DEMO_PASSWORD, seed_catalog
from apps.core.demo.clock import DemoClock, simulated_time
from apps.core.demo.names import make_people
from apps.visits.models import Visit

#: Databases the demo may write.
DEMO_DB_NAME = re.compile(r"^(demo|e2e|test)_[A-Za-z0-9_]+$")

__all__ = ["DEMO_DB_NAME", "Command", "require_demo_database"]


def require_demo_database() -> str:
    name = str(connection.settings_dict.get("NAME") or "")
    if not DEMO_DB_NAME.match(name):
        raise CommandError(
            f"Refusing to run seed_demo on {name!r}: it writes demo accounts with a known "
            "password and a month of invented activity. Use a database named demo_*, e2e_* or "
            "test_* (make demo creates demo_hospital)."
        )
    return name


class Command(BaseCommand):
    help = "Load the demo center: catalog, 500 patients and a month of activity (demo DBs only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--seed", type=int, default=2026, help="Random seed (default 2026).")
        parser.add_argument("--days", type=int, default=30, help="Days of history (default 30).")
        parser.add_argument("--patients", type=int, default=500, help="Patients (default 500).")
        parser.add_argument(
            "--visits-per-day", type=int, default=42, help="Visits on a weekday (default 42)."
        )

    def _progress(self, began: float, verbosity: int) -> Callable[[date, Summary], None] | None:
        """One line per played day (``-v 0`` silences it)."""
        if verbosity < 1:
            return None

        def report(day: date, summary: Summary) -> None:
            seconds = clock_time.monotonic() - began
            self.stdout.write(
                f"seed_demo: {day} played ({summary.counts['visits']} visits so far, "
                f"{seconds:.0f} s)"
            )
            self.stdout.flush()

        return report

    def handle(self, *args: Any, **options: Any) -> None:
        db = require_demo_database()
        days = int(options["days"])
        if not 1 <= days <= 120:
            raise CommandError("--days must be between 1 and 120")
        seed = int(options["seed"])
        rng = random.Random(seed)
        began = clock_time.monotonic()
        now = timezone.now()
        today = timezone.localdate(now)
        start = today - timedelta(days=days)
        # The month starts at 07:00 on its first day; today's activity stops just before now.
        clock = DemoClock(
            datetime.combine(start, datetime.min.time(), tzinfo=timezone.get_current_timezone())
            + timedelta(hours=7)
        )
        cutoff = now - timedelta(minutes=2)
        has_activity = Visit.objects.exists()
        with (
            transaction.atomic(),
            pghistory.context(command="seed_demo", seed=seed),
            simulated_time(clock),
        ):
            catalog = seed_catalog(on=start, rng=rng)
            summary = None
            if not has_activity:
                people = make_people(rng, int(options["patients"]), today=start)
                summary = Simulation(
                    cat=catalog,
                    clock=clock,
                    rng=rng,
                    people=people,
                    start=start,
                    days=days,
                    visits_per_day=int(options["visits_per_day"]),
                    cutoff=cutoff,
                ).run(progress=self._progress(began, int(options["verbosity"])))
        elapsed = clock_time.monotonic() - began
        made = ", ".join(f"{k} {v}" for k, v in sorted(catalog.created.items())) or "nothing new"
        self.stdout.write(f"seed_demo: database {db}, seed {seed}, {start} to {today}")
        self.stdout.write(f"seed_demo: configuration: {made}")
        if summary is None:
            self.stdout.write(
                self.style.WARNING(
                    "seed_demo: the database already has visits; the activity was not made again"
                )
            )
        else:
            counts = ", ".join(f"{k} {v}" for k, v in sorted(summary.counts.items()))
            self.stdout.write(f"seed_demo: activity: {counts}")
        self.stdout.write(
            self.style.SUCCESS(
                f"seed_demo: done in {elapsed:.0f} s. Sign in as reception, cashier, cashsup, "
                f"pharmacist, labtech, labsup, nurse, accountant, manager, admin or a doctor "
                f"(dr.hamid ...) with the demo password {DEMO_PASSWORD}."
            )
        )
