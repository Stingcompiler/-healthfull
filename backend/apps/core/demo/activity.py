"""A month of center activity, played day by day through the services (ADR 0017).

The simulation keeps a time-ordered event queue. Each event moves the simulated clock to its
time and calls the service a real screen would call, as the user who would act: reception
registers and opens visits, the cashier on shift invoices and takes money, doctors write
notes and order, the lab receives, enters and approves, the nurse performs procedures, the
pharmacist dispenses FEFO, supervisors confirm and reject transfers and approve credit notes
and refunds, the manager reviews shifts, the accountant builds and follows claims. Nothing is
written to a money, stock or clinical table directly, so every invariant and database guard
holds for the demo data exactly as for real data.

Every random choice comes from one seeded ``random.Random``: the same seed, start day and
volumes give the same month.
"""

from __future__ import annotations

import heapq
import itertools
import random
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any

import pghistory
from django.db import transaction
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import DocumentStatus, Invoice, InvoiceLine
from apps.catalog import services as catalog_services
from apps.claims import services as claims
from apps.claims.models import Claim, ClaimLine
from apps.clinical import services as clinical
from apps.core.demo import data
from apps.core.demo.catalog import Catalog
from apps.core.demo.clock import DemoClock
from apps.core.demo.names import Person
from apps.core.models import DoctorProfile, User
from apps.lab import services as lab
from apps.lab.models import LabParameter, LabTest
from apps.orders import services as orders
from apps.orders.models import BillingStatus, FulfilmentStatus, ServiceLine
from apps.patients import services as patients
from apps.patients.models import Patient
from apps.payments import services as payments
from apps.payments.models import Payment, PaymentMethod, Shift, ShiftStatus, Verification
from apps.pharmacy import services as pharmacy
from apps.pharmacy.models import Batch, StockBalance
from apps.visits import services as visits
from apps.visits.models import (
    ACTIVE_QUEUE_STATUSES,
    Admission,
    AdmissionStatus,
    Bed,
    BedStatus,
    QueueEntry,
    Visit,
)
from domain.errors import DomainError
from domain.money import ZERO, q

__all__ = ["COMPLETE_MARK", "Simulation", "Summary"]

TZ = timezone.get_current_timezone

#: The cashier who works each shift, its till and opening float.
MORNING = ("cashier", "T1", Decimal("20000.00"))
EVENING = ("cashier2", "T2", Decimal("15000.00"))
SWITCH = time(14, 0)

#: Note of the cash price version for the 1st of next month: the last write of a run, so it
#: marks a complete demo month (``seed_demo`` refuses to build on an interrupted one).
COMPLETE_MARK = "زيادة مجدولة (بيانات تجريبية)"


@dataclass(slots=True)
class Summary:
    counts: Counter[str] = field(default_factory=Counter)
    #: Wall seconds spent per kind of event (``seed_demo -v 2`` prints them).
    seconds: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))

    def add(self, what: str, n: int = 1) -> None:
        self.counts[what] += n


@dataclass(slots=True)
class VisitCtx:
    visit: Visit
    patient: Patient
    doctor: DoctorProfile
    scenario: data.Scenario | None = None
    lab_lines: list[int] = field(default_factory=list)
    procedure_lines: list[int] = field(default_factory=list)
    drug_lines: list[int] = field(default_factory=list)


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ())


class Simulation:
    """One month (``days`` full days ending yesterday, then today up to ``cutoff``)."""

    def __init__(
        self,
        *,
        cat: Catalog,
        clock: DemoClock,
        rng: random.Random,
        people: list[Person],
        start: date,
        days: int,
        visits_per_day: int,
        cutoff: datetime,
    ) -> None:
        self.cat = cat
        self.clock = clock
        self.rng = rng
        self.people = list(people)
        self.start = start
        self.days = days
        self.today = start + timedelta(days=days)
        self.visits_per_day = visits_per_day
        self.cutoff = cutoff
        self.summary = Summary()
        #: The tills' counting has its own stream, so how many shifts close with a variance
        #: does not hinge on how many draws the visits happened to make before each close.
        self.till_rng = random.Random(rng.getrandbits(64))
        self._queue: list[tuple[datetime, int, Callable[..., None], tuple[Any, ...]]] = []
        self._seq = itertools.count()
        self.registered: list[Patient] = []
        self.allergic: dict[int, set[str]] = {}
        self.busy: dict[int, date] = {}
        self.transfers: list[tuple[int, date]] = []
        self.ref_seq = itertools.count(1)
        self.admissions = 0
        self.lab_params: dict[int, list[LabParameter]] = {}
        self.lab_tests: dict[int, LabTest] = {}
        self.drug_classes: dict[str, set[str]] = {
            d.service_code: set(d.classes) for d in data.DRUGS
        }

    # --- users ------------------------------------------------------------------------------------

    def u(self, username: str) -> User:
        return self.cat.users[username]

    def cashier_at(self, when: datetime) -> User | None:
        """The cashier whose shift is open at ``when`` (morning, then evening)."""
        local = timezone.localtime(when)
        if local.time() < time(7, 45) or local.time() >= time(21, 0):
            return None
        name = MORNING[0] if local.time() < SWITCH else EVENING[0]
        user = self.u(name)
        return user if payments.current_shift(user) is not None else None

    # --- event queue ------------------------------------------------------------------------------

    def schedule(self, when: datetime, fn: Callable[..., None], *args: Any) -> None:
        if when > self.cutoff:
            return
        heapq.heappush(self._queue, (when, next(self._seq), fn, args))

    def run(self, progress: Callable[[date, Summary], None] | None = None) -> Summary:
        """Play every day, one transaction per day.

        One transaction for the whole month would keep every superseded row version alive
        until the end (a sequence row updated thousands of times, service lines updated at
        each step), and each lookup would walk those chains: a run gets slower every day. A
        day per transaction lets PostgreSQL prune them. The next-month price version is the
        last write, so its presence marks a complete run (``seed_demo`` checks it).
        """
        for offset in range(self.days + 1):
            day = self.start + timedelta(days=offset)
            with transaction.atomic():
                self._plan_day(day)
                day_end = _at(day, 23, 59)
                while self._queue and self._queue[0][0] <= day_end:
                    when, _, fn, args = heapq.heappop(self._queue)
                    self.clock.set(when)
                    started = perf_counter()
                    # A fresh audit context per event: one context shared by the whole run
                    # would be one row rewritten at every audited write.
                    with pghistory.context(command="seed_demo", event=fn.__name__):
                        fn(*args)
                    self.summary.seconds[fn.__name__] += perf_counter() - started
            if progress is not None:
                progress(day, self.summary)
        self.clock.set(self.cutoff)
        with transaction.atomic(), pghistory.context(command="seed_demo", event="next_month"):
            self._schedule_next_month_prices()
        return self.summary

    # --- the day's plan ----------------------------------------------------------------------

    def _plan_day(self, day: date) -> None:
        index = (day - self.start).days
        friday = day.weekday() == data.FRI
        self.schedule(_at(day, 6, 0), self.charge_nights, day)
        if not friday:
            self.schedule(_at(day, 7, 45), self.open_shift, MORNING)
            self.schedule(_at(day, 14, 10), self.close_shift, MORNING[0], day)
        self.schedule(
            _at(day, 13, 55) if not friday else _at(day, 15, 45), self.open_shift, EVENING
        )
        self.schedule(_at(day, 21, 0), self.close_shift, EVENING[0], day)
        self.schedule(_at(day, 9, 0), self.verify_transfers, day)
        self.schedule(_at(day, 10, 30), self.review_shifts, day)
        self.schedule(_at(day, 11, 15), self.book_appointments, day)
        self.schedule(_at(day, 20, 40), self.end_of_day, day)
        if index == 10:
            self.schedule(_at(day, 9, 30), self.stock_transfer)
        if index == 14:
            self.schedule(_at(day, 10, 0), self.build_claim, "WAHA", 0, 13)
        if index == 14 and self.days >= 16:
            # Effective tomorrow, which is still in the past: the version for the 1st of next
            # month (the run's last write) never collides with it.
            self.schedule(_at(day, 17, 0), self.price_review, day)
        if index == 15:
            self.schedule(_at(day, 11, 0), self.submit_claim, "WAHA")
        if index == 16:
            self.schedule(_at(day, 10, 0), self.restock, day)
        if index == 19:
            self.schedule(_at(day, 10, 0), self.build_claim, "SALAM", 0, 18)
        if index == 20:
            self.schedule(_at(day, 11, 0), self.submit_claim, "SALAM")
            self.schedule(_at(day, 12, 0), self.stock_adjustment)
        if index == 21:
            self.schedule(_at(day, 12, 0), self.claim_responses, "WAHA")
        if index == 22:
            self.schedule(_at(day, 12, 0), self.resolve_rejections, "WAHA")
        if index == 24:
            self.schedule(_at(day, 10, 0), self.build_claim, "AMAL", 0, 23)
        if index == 25:
            self.schedule(_at(day, 11, 0), self.payer_payment, "WAHA", day)

        count = self.visits_per_day if not friday else max(4, self.visits_per_day // 4)
        count = max(1, int(count * self.rng.uniform(0.8, 1.15)))
        doctors = [d for d in data.DOCTORS if any(day.weekday() in s.weekdays for s in d.sessions)]
        weights = [3 if d.department in ("GEN", "PED") else 2 for d in doctors]
        for _ in range(count):
            doc = self.rng.choices(doctors, weights)[0]
            session = self.rng.choice([s for s in doc.sessions if day.weekday() in s.weekdays])
            start = datetime.combine(day, session.start, tzinfo=TZ())
            span = (
                datetime.combine(day, session.end, tzinfo=TZ()) - start - timedelta(minutes=40)
            ).total_seconds()
            when = start + timedelta(seconds=self.rng.uniform(0, max(span, 600)))
            self.schedule(when, self.arrive, doc.username, day)

    # --- shifts -----------------------------------------------------------------------------------

    def open_shift(self, spec: tuple[str, str, Decimal]) -> None:
        name, till_code, opening = spec
        user = self.u(name)
        if payments.current_shift(user) is not None:
            return
        from apps.payments.models import Till

        payments.open_shift(user, opening, till=Till.objects.get(code=till_code))
        self.summary.add("shifts")

    def close_shift(self, name: str, day: date) -> None:
        user = self.u(name)
        shift = payments.current_shift(user)
        if shift is None:
            return
        expected = payments.expected_cash(shift)
        rng = self.till_rng
        roll = rng.random()
        if roll < 0.10:
            short = rng.choice([Decimal(500), Decimal(1000), Decimal(2000), Decimal(5000)])
            counted = max(ZERO, expected - short)
            reason, note = rng.choice(
                [("COUNTING_ERROR", ""), ("CHANGE_ERROR", ""), ("UNEXPLAINED", "لم يُعرف السبب")]
            )
        elif roll < 0.15:
            counted = expected + rng.choice([Decimal(500), Decimal(1000)])
            reason, note = "UNRECORDED_PAYMENT", ""
        else:
            counted, reason, note = expected, None, ""
        if counted != expected:
            self.summary.add("shift_variances")
        payments.close_shift(shift, counted, actor=user, reason=reason, note=note)

    def review_shifts(self, day: date) -> None:
        """The manager signs off yesterday's closed shifts (the last two days stay open)."""
        if (self.today - day).days <= 2:
            return
        manager = self.u("manager")
        yesterday = day - timedelta(days=1)
        for shift in Shift.objects.filter(
            status=ShiftStatus.CLOSED,
            opened_at__date=yesterday,
            review__isnull=True,
        ).order_by("id"):
            if shift.cashier_id == manager.pk:
                continue
            variance = shift.variance or ZERO
            if abs(variance) >= 2000:
                payments.review_shift(
                    shift, actor=manager, outcome="flagged", note="فرق كبير: يُراجع مع الكاشير"
                )
            else:
                payments.review_shift(shift, actor=manager, note="")
            self.summary.add("shift_reviews")

    # --- patients ---------------------------------------------------------------------------------

    def _age_years(self, person_dob: date, on: date) -> float:
        return (on - person_dob).days / 365.25

    def _fits(self, dept: str, sex: str, age: float) -> bool:
        if dept == "PED":
            return age < 14
        if dept == "GYN":
            return sex == "female" and 16 <= age <= 55
        if dept == "INT":
            return age >= 18
        return True

    def _new_patient(self, dept: str, day: date) -> Patient | None:
        for i, person in enumerate(self.people):
            if self._fits(dept, person.sex, self._age_years(person.date_of_birth, day)):
                self.people.pop(i)
                return self._register(person)
        return None

    def _register(self, person: Person) -> Patient:
        reception = self.u("reception")
        patient = patients.register_patient(
            patients.PatientData(
                sex=person.sex,
                full_name_ar=person.full_name_ar,
                full_name_en=person.full_name_en,
                date_of_birth=person.date_of_birth,
                phone=person.phone,
                address=person.address,
            ),
            actor=reception,
            confirm_not_duplicate=True,
        )
        roll = self.rng.random()
        edge = 0.0
        for p in data.PAYERS:
            edge += p.share
            if roll < edge:
                card = f"{p.code}-{self.rng.randrange(10**6):06d}" if p.requires_card_number else ""
                patients.add_coverage(
                    patient, payer=self.cat.payers[p.code], actor=reception, card_number=card
                )
                break
        allergy = self.rng.random()
        klass = None
        if allergy < 0.05:
            klass = "PENICILLIN"
        elif allergy < 0.07:
            klass = "NSAID"
        elif allergy < 0.08:
            klass = "SULFONAMIDE"
        if klass is not None:
            from apps.pharmacy.models import DrugClass

            clinical.record_allergy(
                patient,
                actor=self.u("nurse"),
                allergen_type="drug_class",
                drug_class=DrugClass.objects.get(code=klass),
                reaction="طفح جلدي",
                severity="moderate",
            )
            self.allergic[patient.pk] = {klass}
        self.registered.append(patient)
        self.summary.add("patients")
        return patient

    def _returning_patient(self, dept: str, day: date) -> Patient | None:
        candidates = [
            p
            for p in self.registered
            if self.busy.get(p.pk) != day
            and p.date_of_birth is not None
            and self._fits(dept, p.sex, self._age_years(p.date_of_birth, day))
        ]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _patient_for(self, dept: str, day: date) -> Patient | None:
        remaining_days = max(1, (self.today - day).days)
        want_new = self.people and (
            self.rng.random() < len(self.people) / (remaining_days * self.visits_per_day * 0.85)
            or len(self.registered) < 30
        )
        patient = self._new_patient(dept, day) if want_new else None
        return patient or self._returning_patient(dept, day) or self._new_patient(dept, day)

    # --- the visit --------------------------------------------------------------------------------

    def arrive(self, doctor_username: str, day: date) -> None:
        doc_def = next(d for d in data.DOCTORS if d.username == doctor_username)
        patient = self._patient_for(doc_def.department, day)
        if patient is None:
            return
        self.busy[patient.pk] = day
        doctor = self.cat.doctors[doctor_username]
        visit = visits.create_visit(
            patient=patient,
            actor=self.u("reception"),
            doctor=doctor,
            use_default_coverage=True,
        )
        self.summary.add("visits")
        ctx = VisitCtx(visit=visit, patient=patient, doctor=doctor)
        self.schedule(self._later(3, 9), self.pay_fee, ctx)

    def _later(self, low: int, high: int) -> datetime:
        return self.clock.peek() + timedelta(minutes=self.rng.uniform(low, high))

    def _reference(self, bank: str) -> str:
        return f"{bank}{self.clock.today():%y%m%d}{next(self.ref_seq):05d}"

    def _pay(self, invoice: Invoice, *, transfer_share: float, note: str = "") -> Payment | None:
        """Take the invoice's outstanding patient share in one payment."""
        due = billing.invoice_position(invoice).outstanding
        if due <= 0:
            return None
        cashier = self.cashier_at(self.clock.peek())
        if cashier is None:
            return None
        shift = payments.current_shift(cashier)
        assert shift is not None  # noqa: S101 - cashier_at checked it
        if self.rng.random() < transfer_share:
            bank = self.rng.choice(["BOK", "BOK", "BOK", "FIB", "ONB"])
            payment = payments.record_payment(
                shift,
                invoice.patient,
                PaymentMethod.BANK_TRANSFER,
                due,
                actor=cashier,
                bank=self.cat.banks[bank],
                reference=self._reference(bank),
                transfer_date=self.clock.today(),
                sender_name=invoice.patient.full_name_en,
                allocations=[(invoice, due)],
                note=note,
            )
            self.transfers.append((payment.pk, self.clock.today()))
            self.summary.add("transfers")
        else:
            payment = payments.record_payment(
                shift,
                invoice.patient,
                PaymentMethod.CASH,
                due,
                actor=cashier,
                allocations=[(invoice, due)],
                note=note,
            )
            self.summary.add("cash_payments")
        return payment

    def pay_fee(self, ctx: VisitCtx) -> None:
        cashier = self.cashier_at(self.clock.peek())
        if cashier is None:
            return
        if billing.unbilled_lines(ctx.visit).exists():
            draft = billing.create_draft_invoice(ctx.visit, cashier)
            if self.rng.random() < 0.03:
                line = draft.lines.order_by("line_no").first()
                if line is not None and line.patient_share > 0:
                    billing.apply_discount(
                        line,
                        actor=cashier,
                        approver=self.u("cashsup"),
                        reason=self.rng.choice(["HARDSHIP", "STAFF"]),
                        percent=Decimal(self.rng.choice([10, 20, 25])),
                    )
                    self.summary.add("discounts")
            invoice = billing.approve_invoice(draft, actor=cashier)
            self.summary.add("invoices")
            self._pay(invoice, transfer_share=0.12)
        if self.rng.random() < 0.015:
            self.schedule(self._later(90, 150), self.no_show, ctx)
            return
        self.schedule(self._later(10, 50), self.consult, ctx)

    def no_show(self, ctx: VisitCtx) -> None:
        entry = self._entry(ctx.visit)
        if entry is not None:
            visits.mark_no_show(entry, actor=self.u("reception"))
            self.summary.add("no_shows")

    def _entry(self, visit: Visit) -> QueueEntry | None:
        return QueueEntry.objects.filter(visit=visit, status__in=ACTIVE_QUEUE_STATUSES).first()

    def _scenario(self, dept: str, patient: Patient, day: date) -> data.Scenario:
        assert patient.date_of_birth is not None  # noqa: S101 - demo patients have one
        age = self._age_years(patient.date_of_birth, day)
        options = [
            s
            for s in data.SCENARIOS[dept]
            if not (s.adults_only and age < 16) and not (s.children and age >= 14)
        ] or list(data.SCENARIOS[dept])
        return self.rng.choices(options, [s.weight for s in options])[0]

    def _rx_items(self, scenario: data.Scenario, patient: Patient) -> list[dict[str, Any]]:
        allergic = self.allergic.get(patient.pk, set())
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rx in scenario.rx:
            code = rx.drug
            if self.drug_classes.get(f"DRG-{code}", set()) & allergic:
                code = data.ALLERGY_SUBSTITUTES.get(code, "")
                if not code or self.drug_classes.get(f"DRG-{code}", set()) & allergic:
                    continue
            service_code = f"DRG-{code}"
            if service_code in seen:
                continue
            seen.add(service_code)
            prescription: dict[str, Any] = {
                "dose": rx.dose,
                "route": rx.route,
                "frequency_code": rx.frequency,
                "duration_days": rx.days,
            }
            if rx.dose_quantity is not None:
                prescription["dose_quantity"] = Decimal(rx.dose_quantity)
            item: dict[str, Any] = {
                "service": self.cat.services[service_code],
                "prescription": prescription,
            }
            if rx.quantity is not None:
                item["quantity"] = Decimal(rx.quantity)
            items.append(item)
        return items

    def consult(self, ctx: VisitCtx) -> None:
        entry = self._entry(ctx.visit)
        if entry is None:
            return
        doctor = ctx.doctor.user
        day = self.clock.today()
        visits.call_patient(entry, actor=doctor)
        visits.start_consultation(entry, actor=doctor)
        if self.rng.random() < 0.6:
            systolic = self.rng.randint(100, 165)
            clinical.record_vitals(
                ctx.visit,
                actor=self.u("nurse"),
                temperature_c=Decimal(str(round(self.rng.uniform(36.4, 39.2), 1))),
                pulse_bpm=self.rng.randint(68, 112),
                bp_systolic=systolic,
                bp_diastolic=systolic - self.rng.randint(30, 55),
            )
        scenario = self._scenario(ctx.doctor.department.code, ctx.patient, day)
        ctx.scenario = scenario
        note = clinical.save_note(
            ctx.visit,
            actor=doctor,
            complaint=scenario.complaint_ar,
            assessment=scenario.text_en,
            plan=scenario.plan_ar,
        )
        clinical.sign_note(note, actor=doctor)
        code = scenario.icd10 if clinical.icd10_by_code(scenario.icd10) is not None else None
        clinical.add_diagnosis(
            ctx.visit,
            actor=doctor,
            icd10_code=code,
            text=scenario.text_en,
            certainty="confirmed" if scenario.labs else "provisional",
        )
        items: list[dict[str, Any]] = []
        labs = [*scenario.labs, *(x for x in scenario.extra_labs if self.rng.random() < 0.35)]
        for code in dict.fromkeys(labs):
            items.append({"service": self.cat.services[f"LAB-{code}"]})
        for code in scenario.procedures:
            items.append({"service": self.cat.services[code]})
        items.extend(self._rx_items(scenario, ctx.patient))
        if items:
            for line in clinical.order_lines(ctx.visit, items, actor=doctor):
                if line.kind == "lab":
                    ctx.lab_lines.append(line.pk)
                elif line.kind == "procedure":
                    ctx.procedure_lines.append(line.pk)
                else:
                    ctx.drug_lines.append(line.pk)
            self.summary.add("orders", len(items))
        visits.finish_consultation(entry, actor=doctor)
        if self._wants_admission(ctx, scenario):
            self.schedule(self._later(20, 40), self.admit, ctx)
        if items:
            roll = self.rng.random()
            if roll < 0.03:
                self.summary.add("left_unbilled")
                return
            self.schedule(self._later(4, 15), self.pay_services, ctx, roll < 0.05)

    # --- billing of the orders --------------------------------------------------------------------

    def pay_services(self, ctx: VisitCtx, leave_unpaid: bool) -> None:
        cashier = self.cashier_at(self.clock.peek())
        if cashier is None:
            return
        unbilled = list(billing.unbilled_lines(ctx.visit).select_related("service"))
        if not unbilled:
            return
        if len(unbilled) > 1 and self.rng.random() < 0.04:
            refused = self.rng.choice([ln for ln in unbilled if ln.kind != "consultation"])
            orders.cancel_line(refused, "PATIENT_REFUSED", cashier)
            self.summary.add("refused_lines")
        if not billing.unbilled_lines(ctx.visit).exists():
            return
        draft = billing.create_draft_invoice(ctx.visit, cashier)
        for il in draft.lines.select_related("service"):
            if il.service.code == "GYN-US" and il.payer_id is not None:
                billing.set_preapproval_ref(
                    il, f"PA-{self.rng.randrange(10**5):05d}", actor=cashier
                )
        invoice = billing.approve_invoice(draft, actor=cashier)
        self.summary.add("invoices")
        if leave_unpaid:
            self.summary.add("left_unpaid")
            return
        self._pay(invoice, transfer_share=0.25)
        self._schedule_work(ctx)
        if self.rng.random() < 0.025:
            self.schedule(self._later(10, 25), self.change_of_mind, ctx)

    def _schedule_work(self, ctx: VisitCtx) -> None:
        if ctx.lab_lines:
            self.schedule(self._later(5, 20), self.lab_receive, ctx)
        if ctx.procedure_lines:
            self.schedule(self._later(10, 35), self.procedures, ctx)
        if ctx.drug_lines:
            self.schedule(self._later(5, 25), self.dispense, ctx)

    def change_of_mind(self, ctx: VisitCtx) -> None:
        """The patient no longer wants a paid test or procedure: credit note, then refund."""
        cashier = self.cashier_at(self.clock.peek())
        if cashier is None:
            return
        candidates = list(
            ServiceLine.objects.filter(
                pk__in=[*ctx.lab_lines, *ctx.procedure_lines],
                billing_status=BillingStatus.SETTLED,
                fulfilment_status=FulfilmentStatus.PENDING,
            )
        )
        if not candidates:
            return
        line = self.rng.choice(candidates)
        il = (
            InvoiceLine.objects.filter(service_line=line, invoice__status=DocumentStatus.APPROVED)
            .select_related("invoice")
            .first()
        )
        if il is None or il.patient_share <= 0:
            return
        note = billing.create_credit_note(
            il.invoice,
            [(il, int(il.quantity))],
            actor=cashier,
            reason="SERVICE_CANCELLED",
            note="المريض لا يرغب في الخدمة",
        )
        outcome = billing.approve_credit_note(
            note, actor=self.u("cashsup"), open_refund=True, refund_requested_by=cashier
        )
        self.summary.add("credit_notes")
        refund = outcome.refund
        if refund is None:
            return
        try:
            refund = payments.approve_refund(refund, actor=self.u("cashsup"), note="تمت المراجعة")
        except DomainError as exc:
            # Paid by a transfer still pending: the refund waits until the money is confirmed.
            if exc.code != "REFUND_EXCEEDS_CREDIT":
                raise
            self.summary.add("refunds_waiting")
            return
        try:
            payments.pay_refund(refund, actor=cashier)
            self.summary.add("refunds_paid")
        except DomainError as exc:
            if exc.code != "CASH_INSUFFICIENT":
                raise
            self.summary.add("refunds_waiting")

    # --- the departments --------------------------------------------------------------------------

    def _eligible(self, ids: Iterable[int]) -> list[ServiceLine]:
        return [
            ln
            for ln in ServiceLine.objects.filter(pk__in=list(ids)).select_related("service")
            if ln.fulfilment_status in (FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS)
            and (ln.billing_status == BillingStatus.SETTLED or ln.authorization_id is not None)
        ]

    def lab_receive(self, ctx: VisitCtx) -> None:
        lines = [ln for ln in self._eligible(ctx.lab_lines) if ln.fulfilment_status == "pending"]
        if not lines:
            return
        by_type: dict[str, list[ServiceLine]] = {}
        for ln in lines:
            test = self._test(ln.service_id)
            by_type.setdefault(test.sample_type, []).append(ln)
        for group in by_type.values():
            lab.collect_and_receive(visit=ctx.visit, lines=group, actor=self.u("labtech"))
        self.summary.add("samples", len(by_type))
        self.schedule(self._later(25, 90), self.lab_enter, ctx)

    def _test(self, service_id: int) -> LabTest:
        if service_id not in self.lab_tests:
            self.lab_tests[service_id] = LabTest.objects.get(service_id=service_id)
        return self.lab_tests[service_id]

    def _params(self, test: LabTest) -> list[LabParameter]:
        if test.pk not in self.lab_params:
            self.lab_params[test.pk] = list(
                test.parameters.filter(active=True).prefetch_related("reference_ranges")
            )
        return self.lab_params[test.pk]

    def _value(self, param: LabParameter, scenario: data.Scenario | None) -> str:
        abnormal = self.rng.random() < 0.18
        if param.value_type == "pos_neg":
            positive = abnormal
            if scenario is not None and scenario.icd10 == "B54" and param.code in ("MP", "ICT"):
                positive = self.rng.random() < 0.8
            return "positive" if positive else "negative"
        if param.value_type == "choice":
            choices = list(param.choices)
            return self.rng.choice(choices[1:]) if abnormal and len(choices) > 1 else choices[0]
        if param.value_type == "text":
            ranges = list(param.reference_ranges.all())
            return ranges[0].normal_text if ranges and ranges[0].normal_text else "normal"
        ranges = list(param.reference_ranges.all())
        low = next((r.low for r in ranges if r.low is not None), None)
        high = next((r.high for r in ranges if r.high is not None), None)
        if low is None and high is None:
            low, high = Decimal(1), Decimal(10)
        elif low is None:
            low = (high or Decimal(1)) * Decimal("0.3")
        elif high is None:
            high = low * Decimal("1.8")
        assert low is not None  # noqa: S101
        assert high is not None  # noqa: S101
        span = high - low
        if abnormal:
            value = high + span * Decimal(str(self.rng.uniform(0.05, 0.6)))
            if self.rng.random() < 0.4 and low > 0:
                value = low - span * Decimal(str(self.rng.uniform(0.05, 0.3)))
                value = max(value, low * Decimal("0.3"))
        else:
            value = low + span * Decimal(str(self.rng.uniform(0.1, 0.9)))
        step = Decimal(1).scaleb(-param.decimals)
        return str(value.quantize(step))

    def lab_enter(self, ctx: VisitCtx) -> None:
        lines = [
            ln for ln in self._eligible(ctx.lab_lines) if ln.fulfilment_status == "in_progress"
        ]
        if not lines:
            return
        tech = self.u("labtech")
        entered: list[int] = []
        for ln in lines:
            if self.rng.random() < 0.006:
                lab.cannot_perform(
                    ln,
                    actor=tech,
                    reason_code="EQUIPMENT_DOWN",
                    note="الجهاز في الصيانة",
                    approver=self.u("cashsup"),
                )
                self.summary.add("lab_cannot_perform")
                continue
            test = self._test(ln.service_id)
            values = {p.code: self._value(p, ctx.scenario) for p in self._params(test)}
            lab.enter_results(ln, values=values, actor=tech)
            entered.append(ln.pk)
        self.summary.add("results_entered", len(entered))
        if entered:
            when = self._later(15, 120)
            if timezone.localtime(when).time() > time(20, 45):
                when = _at(self.clock.today() + timedelta(days=1), 8, 30)
            self.schedule(when, self.lab_approve, entered)

    def lab_approve(self, line_ids: list[int]) -> None:
        sup = self.u("labsup")
        for ln in ServiceLine.objects.filter(pk__in=line_ids):
            if ln.fulfilment_status != FulfilmentStatus.IN_PROGRESS:
                continue
            lab.approve_results(ln, actor=sup)
            self.summary.add("results_approved")

    def procedures(self, ctx: VisitCtx) -> None:
        for ln in self._eligible(ctx.procedure_lines):
            orders.perform_procedure(ln, self.u("nurse"), note="")
            self.summary.add("procedures")

    def dispense(self, ctx: VisitCtx) -> None:
        lines = self._eligible(ctx.drug_lines)
        if not lines:
            return
        requests = []
        for ln in lines:
            open_units = orders.open_units(ln)
            if open_units > 0:
                requests.append(
                    pharmacy.DispenseRequest(service_line_id=ln.pk, quantity=open_units)
                )
        if not requests:
            return
        try:
            pharmacy.dispense(
                visit=ctx.visit,
                store=self.cat.stores["PHA"],
                actor=self.u("pharmacist"),
                requests=requests,
            )
            self.summary.add("dispenses")
            self.summary.add("dispensed_lines", len(requests))
        except DomainError as exc:
            if exc.code != "STOCK_INSUFFICIENT":
                raise
            self.summary.add("dispense_short")

    # --- admissions -------------------------------------------------------------------------------

    def _wants_admission(self, ctx: VisitCtx, scenario: data.Scenario) -> bool:
        if self.admissions >= max(2, self.days // 5):
            return False
        severe = scenario.icd10 in ("B54", "I50.9", "O21.0", "J18.9", "A01.0")
        return severe and self.rng.random() < 0.08

    def admit(self, ctx: VisitCtx) -> None:
        if Admission.objects.filter(patient=ctx.patient, status=AdmissionStatus.ADMITTED).exists():
            return
        wanted = "F-" if ctx.patient.sex == "female" else "M-"
        bed = (
            Bed.objects.filter(code__startswith=wanted, status=BedStatus.AVAILABLE)
            .order_by("code")
            .first()
        )
        if bed is None:
            return
        admission = visits.admit_patient(
            ctx.patient,
            bed=bed,
            doctor=ctx.doctor,
            actor=self.u("nurse"),
            visit=ctx.visit,
            diagnosis=ctx.scenario.text_en if ctx.scenario else "",
        )
        self.admissions += 1
        self.summary.add("admissions")
        # The stay authorization makes the visit's orders workable before payment.
        self._schedule_work(ctx)
        nights = self.rng.randint(1, 3)
        discharge_day = self.clock.today() + timedelta(days=nights)
        self.schedule(_at(discharge_day, 11, 0), self.discharge, admission.pk, ctx)

    def charge_nights(self, day: date) -> None:
        if Admission.objects.filter(status=AdmissionStatus.ADMITTED).exists():
            charged = visits.charge_due_bed_nights(actor=self.u("nurse"), through=day)
            self.summary.add("bed_nights", len(charged))

    def discharge(self, admission_id: int, ctx: VisitCtx) -> None:
        admission = Admission.objects.get(pk=admission_id)
        if admission.status != AdmissionStatus.ADMITTED:
            return
        visits.discharge(admission, actor=self.u("nurse"), summary="تحسن وخروج بحالة مستقرة")
        self.summary.add("discharges")
        self.schedule(self._later(10, 30), self.settle_stay, ctx)

    def settle_stay(self, ctx: VisitCtx) -> None:
        cashier = self.cashier_at(self.clock.peek())
        if cashier is None or not billing.unbilled_lines(ctx.visit).exists():
            return
        invoice = billing.approve_invoice(
            billing.create_draft_invoice(ctx.visit, cashier), actor=cashier
        )
        self.summary.add("invoices")
        self._pay(invoice, transfer_share=0.3)

    # --- transfers --------------------------------------------------------------------------------

    def verify_transfers(self, day: date) -> None:
        """Yesterday's and older pending transfers: most confirmed by the accountant, a few
        rejected by the cashier supervisor (whose own till books the late reversal)."""
        accountant = self.u("accountant")
        recent_cut = self.today - timedelta(days=2)
        to_reject: list[Payment] = []
        keep: list[tuple[int, date]] = []
        for pid, taken in self.transfers:
            if taken >= day or taken >= recent_cut:
                keep.append((pid, taken))
                continue
            payment = Payment.objects.get(pk=pid)
            if payment.verification != Verification.PENDING:
                continue
            roll = self.rng.random()
            if roll < 0.05:
                to_reject.append(payment)
            elif roll < 0.95:
                payments.confirm_transfer(
                    payment, actor=accountant, note="مطابق لكشف الحساب البنكي"
                )
                self.summary.add("transfers_confirmed")
            else:
                keep.append((pid, taken))
        self.transfers = keep
        if to_reject:
            self._reject_late(to_reject)

    def _reject_late(self, rejected: list[Payment]) -> None:
        sup = self.u("cashsup")
        from apps.payments.models import Till

        opened = payments.current_shift(sup) is None
        if opened:
            payments.open_shift(sup, ZERO, till=Till.objects.get(code="T2"), note="رفض تحويلات")
            self.summary.add("shifts")
        for payment in rejected:
            payments.reject_transfer(
                payment, actor=sup, reason="NOT_RECEIVED", note="لم يصل المبلغ إلى الحساب"
            )
            self.summary.add("transfers_rejected")
            patient = Patient.objects.get(pk=payment.patient_id)
            back = self.clock.today() + timedelta(days=self.rng.randint(1, 4))
            self.schedule(
                _at(back, self.rng.randint(9, 12), self.rng.randint(0, 59)),
                self.settle_debt,
                patient,
            )
        if opened:
            shift = payments.current_shift(sup)
            assert shift is not None  # noqa: S101
            payments.close_shift(shift, payments.expected_cash(shift), actor=sup)

    def settle_debt(self, patient: Patient) -> None:
        """The patient whose transfer was rejected comes back and pays in cash."""
        cashier = self.cashier_at(self.clock.peek())
        if cashier is None:
            return
        due = sum((pos.outstanding for _, pos in billing.open_invoices(patient)), ZERO)
        if due <= 0:
            return
        shift = payments.current_shift(cashier)
        assert shift is not None  # noqa: S101
        payments.record_payment(
            shift,
            patient,
            PaymentMethod.CASH,
            due,
            actor=cashier,
            auto=True,
            note="سداد تحويل مرفوض",
        )
        self.summary.add("debts_settled")

    def end_of_day(self, day: date) -> None:
        """Waiting patients who never answered are marked; a confirmed transfer bounces now
        and then (rejected after confirmation, a reversal in the supervisor's till)."""
        for entry in QueueEntry.objects.filter(queue_date=day, status__in=ACTIVE_QUEUE_STATUSES):
            visits.mark_no_show(entry, actor=self.u("reception"))
            self.summary.add("no_shows")
        if (day - self.start).days in (9, 23):
            bounced = (
                Payment.objects.filter(
                    method=PaymentMethod.BANK_TRANSFER,
                    verification=Verification.CONFIRMED,
                    reversal_of__isnull=True,
                )
                .order_by("-id")
                .first()
            )
            if bounced is not None:
                self._reject_late([bounced])

    # --- appointments -----------------------------------------------------------------------------

    def book_appointments(self, day: date) -> None:
        reception = self.u("reception")
        for _ in range(self.rng.randint(2, 5)):
            doc = self.rng.choice(data.DOCTORS)
            ahead = self.rng.randint(1, 7)
            target = day + timedelta(days=ahead)
            sessions = [s for s in doc.sessions if target.weekday() in s.weekdays]
            if not sessions:
                continue
            session = self.rng.choice(sessions)
            slots = int(
                (datetime.combine(target, session.end) - datetime.combine(target, session.start))
                / timedelta(minutes=session.slot_minutes)
            )
            start = datetime.combine(target, session.start, tzinfo=TZ()) + timedelta(
                minutes=session.slot_minutes * self.rng.randrange(max(1, slots))
            )
            patient = self._returning_patient(doc.department, target)
            if patient is None:
                continue
            try:
                appt = visits.book_appointment(
                    doctor=self.cat.doctors[doc.username],
                    starts_at=start,
                    actor=reception,
                    patient=patient,
                    notes="مراجعة",
                )
            except DomainError as exc:
                if exc.code in ("APPOINTMENT_CONFLICT", "OUTSIDE_SCHEDULE"):
                    continue
                raise
            self.summary.add("appointments")
            if self.rng.random() < 0.75:
                self.schedule(
                    start - timedelta(minutes=10), self.arrive_booked, appt.pk, doc.username
                )

    def arrive_booked(self, appointment_id: int, doctor_username: str) -> None:
        from apps.visits.models import Appointment, AppointmentStatus

        appt = Appointment.objects.select_related("patient").get(pk=appointment_id)
        if appt.status != AppointmentStatus.BOOKED or appt.patient is None:
            return
        if self.busy.get(appt.patient.pk) == self.clock.today():
            return
        self.busy[appt.patient.pk] = self.clock.today()
        visit = visits.convert_appointment(appt, actor=self.u("reception"))
        self.summary.add("visits")
        self.summary.add("appointments_kept")
        ctx = VisitCtx(visit=visit, patient=appt.patient, doctor=self.cat.doctors[doctor_username])
        self.schedule(self._later(3, 9), self.pay_fee, ctx)

    # --- pharmacy stock ---------------------------------------------------------------------------

    def restock(self, day: date) -> None:
        pharmacist = self.u("pharmacist")
        receipt = pharmacy.create_receipt(
            supplier=self.cat.suppliers["SUP-NILE"],
            store=self.cat.stores["PHA"],
            actor=pharmacist,
            supplier_invoice_no=f"NIL-{day:%Y%m%d}",
            supplier_invoice_date=day,
            note="توريد منتصف الشهر",
        )
        for d in data.DRUGS:
            if d.popularity < 4:
                continue
            countable = d.unit in ("tablet", "capsule", "sachet")
            pharmacy.add_receipt_line(
                receipt,
                item=self.cat.items[d.service_code],
                batch_no=f"{d.code[:3]}-R{day:%m%d}",
                expiry_date=day + timedelta(days=self.rng.randint(540, 900)),
                quantity=1000 if countable else 60,
                unit_cost=q(Decimal(d.price) * Decimal("0.65")),
                actor=pharmacist,
                today=day,
            )
        pharmacy.post_receipt(receipt, actor=pharmacist, today=day)
        self.summary.add("goods_receipts")

    def stock_transfer(self) -> None:
        """Main store to pharmacy for a few busy items (sent and received the same morning)."""
        pharmacist = self.u("pharmacist")
        lines: list[tuple[int, int]] = []
        for code in ("DRG-PARA500", "DRG-AMOX500", "DRG-COART", "DRG-METRO500", "DRG-OMEP20"):
            balance = (
                StockBalance.objects.filter(
                    item=self.cat.items[code], store=self.cat.stores["MAIN"], qty_base__gt=0
                )
                .order_by("batch__expiry_date")
                .first()
            )
            if balance is not None:
                lines.append((balance.batch_id, min(int(balance.qty_base), 500)))
        if not lines:
            return
        transfer = pharmacy.create_transfer(
            from_store=self.cat.stores["MAIN"],
            to_store=self.cat.stores["PHA"],
            lines=lines,
            actor=pharmacist,
            note="تحويل أسبوعي",
        )
        pharmacy.send_transfer(transfer, actor=pharmacist)
        pharmacy.receive_transfer(transfer, actor=pharmacist)
        self.summary.add("stock_transfers")

    def stock_adjustment(self) -> None:
        item = self.cat.items["DRG-PARASYR"]
        balance = (
            StockBalance.objects.filter(item=item, store=self.cat.stores["PHA"], qty_base__gt=2)
            .order_by("batch__expiry_date")
            .first()
        )
        if balance is None:
            return
        adjustment = pharmacy.request_adjustment(
            store=self.cat.stores["PHA"],
            reason_code="DAMAGED",
            lines=[(balance.batch_id, -2, "زجاجتان مكسورتان")],
            actor=self.u("pharmacist"),
            note="تلف أثناء الترتيب",
        )
        pharmacy.approve_adjustment(adjustment, actor=self.u("manager"))
        self.summary.add("stock_adjustments")

    # --- prices -----------------------------------------------------------------------------------

    def price_review(self, day: date) -> None:
        """Consultation fees go up from tomorrow; invoices approved before keep their prices."""
        cash = catalog_services.default_price_list()
        current = catalog_services.version_prices(catalog_services.effective_version(cash, day))
        by_code = {self.cat.services[c].pk: Decimal(p) for c, p in data.PRICE_REVIEW.items()}
        prices = {sid: by_code.get(sid, price) for sid, price in current.items()}
        catalog_services.create_version(
            cash,
            effective_from=day + timedelta(days=1),
            prices=prices,
            actor=self.u("admin"),
            note="مراجعة أسعار الكشف",
            today=day,
        )
        self.summary.add("price_versions")

    def _schedule_next_month_prices(self) -> None:
        """A +10% cash version waiting for the 1st of next month (FEATURES 5.2)."""
        today = timezone.localdate()
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        cash = catalog_services.default_price_list()
        from apps.catalog.models import PriceListVersion

        if PriceListVersion.objects.filter(price_list=cash, note=COMPLETE_MARK).exists():
            return
        catalog_services.bulk_percentage_update(
            cash,
            percent=Decimal(10),
            effective_from=first,
            actor=self.u("admin"),
            note=COMPLETE_MARK,
            today=today,
        )
        self.summary.add("price_versions")

    # --- claims -----------------------------------------------------------------------------------

    def _claim(self, payer: str) -> Claim | None:
        return Claim.objects.filter(payer=self.cat.payers[payer]).order_by("-id").first()

    def build_claim(self, payer: str, first: int, last: int) -> None:
        try:
            claims.build_claim(
                payer=self.cat.payers[payer],
                period_start=self.start + timedelta(days=first),
                period_end=self.start + timedelta(days=last),
                actor=self.u("accountant"),
                note="مطالبة النصف الأول من الشهر",
            )
        except DomainError as exc:
            if exc.code != "CLAIM_EMPTY":
                raise
            return
        self.summary.add("claims")

    def submit_claim(self, payer: str) -> None:
        claim = self._claim(payer)
        if claim is not None and claim.status == "draft":
            claims.submit_claim(claim, actor=self.u("accountant"))
            self.summary.add("claims_submitted")

    def claim_responses(self, payer: str) -> None:
        claim = self._claim(payer)
        if claim is None or claim.status != "submitted":
            return
        responses = []
        lines = list(ClaimLine.objects.filter(claim=claim).order_by("id"))
        for i, cl in enumerate(lines):
            if i % 11 == 3:
                responses.append(claims.ClaimResponse(cl.pk, ZERO, reason="خدمة غير مشمولة بالعقد"))
            elif i % 11 == 7:
                half = q(cl.amount_claimed / 2)
                responses.append(
                    claims.ClaimResponse(cl.pk, half, reason="تجاوز السقف المتفق عليه")
                )
            else:
                responses.append(claims.ClaimResponse(cl.pk, cl.amount_claimed))
        if responses:
            claims.record_responses(claim, responses, actor=self.u("accountant"))
            self.summary.add("claims_answered")

    def resolve_rejections(self, payer: str) -> None:
        claim = self._claim(payer)
        if claim is None:
            return
        rejected = [
            cl
            for cl in ClaimLine.objects.filter(claim=claim).order_by("id")
            if cl.rejected_amount > 0
        ]
        for i, cl in enumerate(rejected):
            if i % 2 == 0:
                claims.resolve_rejection(
                    cl,
                    resolution="written_off",
                    actor=self.u("accountant"),
                    reason_code="NOT_COVERED",
                    note="شطب حسب العقد",
                )
            else:
                claims.resolve_rejection(
                    cl,
                    resolution="rebilled",
                    actor=self.u("accountant"),
                    reason_code="NOT_COVERED",
                    note="يُحمّل على المريض",
                )
            self.summary.add("claim_rejections_resolved")

    def payer_payment(self, payer: str, day: date) -> None:
        claim = self._claim(payer)
        if claim is None:
            return
        claim.refresh_from_db()
        accepted = claim.accepted_total
        if accepted <= 0:
            return
        claims.record_payer_payment(
            payer=self.cat.payers[payer],
            amount=accepted,
            received_on=day,
            actor=self.u("accountant"),
            method="bank_transfer",
            bank=self.cat.banks["BOK"],
            reference=self._reference("WAH"),
            claim_amounts={claim.pk: accepted},
            note="سداد مطالبة",
        )
        self.summary.add("payer_payments")

    # --- helpers for the summary ------------------------------------------------------------------

    def stock_left(self) -> int:
        return int(sum(b.qty_base for b in StockBalance.objects.all()))

    def batches(self) -> int:
        return Batch.objects.count()
