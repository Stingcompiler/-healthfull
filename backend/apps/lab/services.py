"""Laboratory services: samples, result entry with flags, approval, amendments (FEATURES 9).

Rules come from ``domain.lab`` (reference range choice, flags, result versions):

* The work list holds lab lines that are paid or perform-first authorized (invariant 1).
* Collect a sample for one or more lines of a visit (same sample type), receive it in the
  lab (or reject it with a reason: the lines wait for a new sample). Results are entered on a
  draft version only after the sample is received.
* Each value is judged against the most specific reference range for the patient's sex and
  age on the collection date; the range used and the flag are stored with the value.
* A lab supervisor approves the draft (``lab.approve_results``). The first approval performs
  the service line through ``orders.services.perform_line``. Only approved versions are
  visible to doctors and patients.
* A correction after approval is a new draft version amending the approved one, with a
  reason (``lab.amend_results``); when it is approved the old version becomes ``amended``
  and stays on record.
* A test that cannot be performed is cancelled with a reason through
  ``orders.services.cancel_line``, which opens the credit note and refund flow (FEATURES 9.7).
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import ModuleType
from typing import Any

import pghistory
from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.catalog.models import Service, ServiceKind
from apps.core.models import User
from apps.core.services import next_number, notify_users, require_permission, resolve_reason
from apps.lab.models import (
    LabParameter,
    LabTest,
    RangeSex,
    ReferenceRange,
    ResultFlag,
    ResultSet,
    ResultStatus,
    ResultValue,
    ResultVersion,
    Sample,
    SampleStatus,
    SampleType,
    ValueType,
)
from apps.orders.models import BillingStatus, FulfilmentStatus, PerformAuthorization, ServiceLine
from apps.patients.models import Sex
from apps.visits.models import Visit
from domain import lab as dlab
from domain import service_line as dsl
from domain.audit import Approval
from domain.errors import DomainError

__all__ = [
    "add_reference_range",
    "approve_results",
    "cannot_perform",
    "collect_sample",
    "create_lab_test",
    "critical_flags",
    "enter_results",
    "mark_label_printed",
    "receive_sample",
    "reject_sample",
    "start_amendment",
    "turnaround_minutes",
    "visible_result",
    "worklist",
]

POSITIVE, NEGATIVE = "positive", "negative"


def _orders() -> ModuleType:
    return importlib.import_module("apps.orders.services")


def _authorized(line: ServiceLine) -> bool:
    """Whether the line's authorization is unrevoked (as locked by ``orders.lock_lines``)."""
    auth = line.authorization if line.authorization_id is not None else None
    return auth is not None and auth.revoked_at is None


def _eligible(line: ServiceLine) -> bool:
    try:
        status = dsl.LineStatus(
            dsl.BillingStatus(line.billing_status),
            dsl.FulfilmentStatus(line.fulfilment_status),
            authorized=_authorized(line),
        )
    except DomainError:  # started work whose authorization was revoked behind its back
        return False
    return dsl.can_enter_worklist(status)


def _lab_test(line: ServiceLine) -> LabTest:
    if line.kind != ServiceKind.LAB:
        raise DomainError("LINE_NOT_LAB", "The line is not a lab test", line_id=line.pk)
    test = LabTest.objects.filter(service_id=line.service_id).first()
    if test is None:
        raise DomainError("LAB_TEST_UNKNOWN", "The service has no lab test", line_id=line.pk)
    return test


# --- test catalog ---------------------------------------------------------------------------


def create_lab_test(
    *, service: Service, code: str, sample_type: str, actor: User, **fields: Any
) -> LabTest:
    """A lab test for a catalog service of kind ``lab`` (FEATURES 9.1).

    Raises:
        DomainError: ``SERVICE_NOT_LAB``, ``LAB_TEST_EXISTS``, ``INVALID_SAMPLE_TYPE``.
    """
    if service.kind != ServiceKind.LAB:
        raise DomainError("SERVICE_NOT_LAB", "Lab tests belong to lab services")
    if sample_type not in SampleType.values:
        raise DomainError("INVALID_SAMPLE_TYPE", "Unknown sample type", sample_type=sample_type)
    if LabTest.objects.filter(Q(service=service) | Q(code=code.strip())).exists():
        raise DomainError("LAB_TEST_EXISTS", "The service or code already has a lab test")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="lab test"):
        return LabTest.objects.create(
            service=service, code=code.strip(), sample_type=sample_type, **fields
        )


def add_reference_range(
    parameter: LabParameter,
    *,
    actor: User,
    sex: str = RangeSex.ANY,
    age_min_days: int = 0,
    age_max_days: int | None = None,
    low: Decimal | None = None,
    high: Decimal | None = None,
    critical_low: Decimal | None = None,
    critical_high: Decimal | None = None,
    normal_text: str = "",
) -> ReferenceRange:
    """A reference range, validated by ``domain.lab`` before it is stored (FEATURES 9.1)."""
    if sex not in RangeSex.values:
        raise DomainError("INVALID_REFERENCE_RANGE", "Unknown sex", sex=sex)
    row = ReferenceRange(
        parameter=parameter,
        sex=sex,
        age_min_days=age_min_days,
        age_max_days=age_max_days,
        low=low,
        high=high,
        critical_low=critical_low,
        critical_high=critical_high,
        normal_text=normal_text.strip(),
    )
    _domain_range(row)  # INVALID_REFERENCE_RANGE when inconsistent
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="reference range"):
        row.save()
    return row


# --- work list and samples ------------------------------------------------------------------


def worklist(*, visit: Visit | None = None) -> QuerySet[ServiceLine]:
    """Lab lines that may be worked on now: paid or authorized, not performed or cancelled."""
    active_auth = Exists(
        PerformAuthorization.objects.filter(
            pk=OuterRef("authorization_id"), revoked_at__isnull=True
        )
    )
    qs = (
        ServiceLine.objects.filter(
            kind=ServiceKind.LAB,
            fulfilment_status__in=[FulfilmentStatus.PENDING, FulfilmentStatus.IN_PROGRESS],
        )
        .filter(Q(billing_status=BillingStatus.SETTLED) | active_auth)
        .select_related("visit", "visit__patient", "service")
        .order_by("ordered_at", "id")
    )
    if visit is not None:
        qs = qs.filter(visit=visit)
    return qs


def collect_sample(
    *,
    visit: Visit,
    lines: Sequence[ServiceLine],
    actor: User,
    collected_at: datetime | None = None,
) -> Sample:
    """One sample for one or more lab lines of the visit (FEATURES 9.2).

    Raises:
        DomainError: ``SAMPLE_EMPTY``, ``LINE_NOT_ON_VISIT``, ``LINE_NOT_LAB``,
            ``LAB_TEST_UNKNOWN``, ``LINE_NOT_ELIGIBLE``, ``SAMPLE_TYPE_MISMATCH``,
            ``SAMPLE_ALREADY_COLLECTED``.
    """
    if not lines:
        raise DomainError("SAMPLE_EMPTY", "Choose the tests the sample is for")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="collect sample"):
        locked = _orders().lock_lines(ln.pk for ln in lines)
        tests: dict[int, LabTest] = {}
        for line in locked:
            if line.visit_id != visit.pk:
                raise DomainError("LINE_NOT_ON_VISIT", "The line is on another visit")
            tests[line.pk] = _lab_test(line)
            if not _eligible(line):
                raise DomainError(
                    "LINE_NOT_ELIGIBLE", "The test is neither paid nor authorized", line_id=line.pk
                )
            current = (
                ResultSet.objects.filter(service_line=line, sample__isnull=False)
                .exclude(sample__status=SampleStatus.REJECTED)
                .first()
            )
            if current is not None:
                raise DomainError(
                    "SAMPLE_ALREADY_COLLECTED", "The test already has a sample", line_id=line.pk
                )
        sample_types = {t.sample_type for t in tests.values()}
        if len(sample_types) != 1:
            raise DomainError(
                "SAMPLE_TYPE_MISMATCH",
                "These tests need different samples",
                types=sorted(sample_types),
            )
        sample = Sample.objects.create(
            accession_no=next_number("LAB"),
            visit=visit,
            sample_type=sample_types.pop(),
            collected_at=collected_at or timezone.now(),
            collected_by=actor,
        )
        for line in locked:
            rs, created = ResultSet.objects.get_or_create(
                service_line=line, defaults={"test": tests[line.pk], "sample": sample}
            )
            if not created:
                rs.sample = sample
                rs.save(update_fields=["sample"])
            if line.fulfilment_status == FulfilmentStatus.PENDING:
                # Work has started: the doctor sees it in progress (FEATURES 3.7), and a
                # perform-first authorization can no longer be withdrawn under it.
                _orders().start_line(line, actor, at=sample.collected_at)
    return sample


def mark_label_printed(sample: Sample, *, actor: User) -> Sample:
    """Record that the sample label was printed (FEATURES 9.2)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="sample label"):
        locked = Sample.objects.select_for_update().get(pk=sample.pk)
        locked.label_printed_at = timezone.now()
        locked.save(update_fields=["label_printed_at"])
    return locked


def receive_sample(sample: Sample, *, actor: User) -> Sample:
    """The sample arrived in the lab; results can be entered."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="receive sample"):
        locked = Sample.objects.select_for_update().get(pk=sample.pk)
        if locked.status != SampleStatus.COLLECTED:
            raise DomainError("SAMPLE_NOT_COLLECTED", "Only a collected sample can be received")
        locked.status = SampleStatus.RECEIVED
        locked.received_at = timezone.now()
        locked.received_by = actor
        locked.save(update_fields=["status", "received_at", "received_by"])
    return locked


def reject_sample(sample: Sample, *, actor: User, reason_code: str, note: str = "") -> Sample:
    """Reject an unusable sample with a reason; its tests wait for a new sample."""
    reason = resolve_reason(reason_code, "sample_reject", note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"reject sample: {note}"):
        locked = Sample.objects.select_for_update().get(pk=sample.pk)
        if locked.status == SampleStatus.REJECTED:
            raise DomainError("SAMPLE_REJECTED", "The sample is already rejected")
        if ResultVersion.objects.filter(
            result_set__sample=locked, status__in=[ResultStatus.APPROVED, ResultStatus.AMENDED]
        ).exists():
            raise DomainError("RESULT_APPROVED_IMMUTABLE", "Results from this sample are approved")
        locked.status = SampleStatus.REJECTED
        locked.rejection_reason = reason
        locked.rejection_note = note.strip()[:300]
        locked.save(update_fields=["status", "rejection_reason", "rejection_note"])
    return locked


# --- results --------------------------------------------------------------------------------


def _domain_range(row: ReferenceRange) -> dlab.ReferenceRange:
    sex = None if row.sex == RangeSex.ANY else dlab.Sex(row.sex)
    banded = row.age_max_days is not None or row.age_min_days > 0
    try:
        return dlab.ReferenceRange(
            low=row.low,
            high=row.high,
            critical_low=row.critical_low,
            critical_high=row.critical_high,
            sex=sex,
            age_min_days=row.age_min_days if banded else None,
            age_max_days=row.age_max_days,
        )
    except DomainError as exc:
        exc.details["parameter_id"] = row.parameter_id
        exc.details["range_id"] = row.pk
        raise


def _patient_context(rs: ResultSet) -> tuple[dlab.Sex | None, int | None]:
    patient = rs.service_line.visit.patient
    sex = dlab.Sex(patient.sex) if patient.sex in (Sex.MALE, Sex.FEMALE) else None
    on: date = timezone.localdate(rs.sample.collected_at) if rs.sample else timezone.localdate()
    age = dlab.age_in_days(patient.date_of_birth, on) if patient.date_of_birth else None
    return sex, age


@dataclass(frozen=True, slots=True)
class _Judged:
    numeric: Decimal | None
    text: str
    low: Decimal | None
    high: Decimal | None
    ref_text: str
    flag: str


def _judge(param: LabParameter, raw: Any, sex: dlab.Sex | None, age: int | None) -> _Judged:
    rows = list(param.reference_ranges.all())
    pairs = [(_domain_range(r), r) for r in rows]
    chosen = dlab.select_range([d for d, _ in pairs], sex, age)
    row = next((r for d, r in pairs if d is chosen), None) if chosen is not None else None

    if param.value_type == ValueType.NUMERIC:
        try:
            value = Decimal(str(raw).strip())
        except (InvalidOperation, ValueError):
            raise DomainError(
                "RESULT_VALUE_INVALID", "A number is expected", parameter=param.code
            ) from None
        if not value.is_finite():
            raise DomainError("RESULT_VALUE_INVALID", "A number is expected", parameter=param.code)
        value = value.quantize(Decimal(1).scaleb(-param.decimals))
        flag = dlab.flag(value, chosen)
        return _Judged(
            value,
            "",
            row.low if row else None,
            row.high if row else None,
            row.normal_text if row else "",
            str(flag),
        )

    text = str(raw).strip()
    if not text:
        raise DomainError("RESULT_VALUE_INVALID", "A value is expected", parameter=param.code)
    normal = row.normal_text if row else ""
    if param.value_type == ValueType.CHOICE and text not in (param.choices or []):
        raise DomainError(
            "RESULT_VALUE_INVALID", "Not one of the allowed values", parameter=param.code
        )
    if param.value_type == ValueType.POS_NEG:
        text = text.lower()
        if text not in (POSITIVE, NEGATIVE):
            raise DomainError(
                "RESULT_VALUE_INVALID", "Positive or negative expected", parameter=param.code
            )
        normal = normal or NEGATIVE
    if normal:
        text_flag = ResultFlag.NORMAL if text.lower() == normal.lower() else ResultFlag.ABNORMAL
    else:
        text_flag = ResultFlag.NONE
    return _Judged(None, text[:500], None, None, normal, str(text_flag))


def _result_set(line: ServiceLine) -> ResultSet:
    rs = ResultSet.objects.select_for_update().filter(service_line=line).first()
    if rs is None:
        raise DomainError("SAMPLE_NOT_COLLECTED", "Collect a sample first", line_id=line.pk)
    return rs


def _versions(rs: ResultSet) -> list[ResultVersion]:
    return list(ResultVersion.objects.filter(result_set=rs).order_by("version_no"))


def _domain_versions(versions: Sequence[ResultVersion]) -> list[dlab.ResultVersion]:
    by_id = {v.pk: v.version_no for v in versions}
    return [
        dlab.ResultVersion(
            v.version_no,
            dlab.ResultStatus.DRAFT
            if v.status == ResultStatus.DRAFT
            else dlab.ResultStatus.APPROVED,
            by_id.get(v.amends_id) if v.amends_id else None,
        )
        for v in versions
        if v.status != ResultStatus.AMENDED
    ]


def enter_results(
    line: ServiceLine,
    *,
    values: Mapping[str, Any],
    actor: User,
    comment: str | None = None,
) -> ResultVersion:
    """Enter or correct values (by parameter code) on the draft version (FEATURES 9.3).

    The first draft needs a received sample and a paid or authorized line. Each value is
    flagged against the range for the patient's sex and age.

    Raises:
        DomainError: ``SAMPLE_NOT_COLLECTED``, ``SAMPLE_NOT_RECEIVED``, ``LINE_NOT_ELIGIBLE``,
            ``RESULT_APPROVED_IMMUTABLE`` (start an amendment), ``PARAMETER_UNKNOWN``,
            ``RESULT_VALUE_INVALID``, ``INVALID_REFERENCE_RANGE``.
    """
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="enter results"):
        (locked_line,) = _orders().lock_lines([line.pk])
        rs = _result_set(locked_line)
        versions = _versions(rs)
        draft = next((v for v in versions if v.status == ResultStatus.DRAFT), None)
        if draft is None:
            if any(v.status == ResultStatus.APPROVED for v in versions):
                raise DomainError(
                    "RESULT_APPROVED_IMMUTABLE",
                    "An approved result cannot change; start an amendment",
                )
            if rs.sample is None or rs.sample.status != SampleStatus.RECEIVED:
                raise DomainError("SAMPLE_NOT_RECEIVED", "The sample is not received yet")
            if not _eligible(locked_line):
                raise DomainError("LINE_NOT_ELIGIBLE", "The test is neither paid nor authorized")
            draft = ResultVersion.objects.create(
                result_set=rs, version_no=dlab.first_version().number, entered_by=actor
            )
        params = {p.code: p for p in rs.test.parameters.filter(active=True)}
        unknown = sorted(set(values) - set(params))
        if unknown:
            raise DomainError("PARAMETER_UNKNOWN", "Unknown parameters", parameters=unknown)
        sex, age = _patient_context(rs)
        for code, raw in values.items():
            param = params[code]
            judged = _judge(param, raw, sex, age)
            ResultValue.objects.update_or_create(
                version=draft,
                parameter=param,
                defaults={
                    "value_numeric": judged.numeric,
                    "value_text": judged.text,
                    "unit": param.unit,
                    "reference_low": judged.low,
                    "reference_high": judged.high,
                    "reference_text": judged.ref_text,
                    "flag": judged.flag,
                },
            )
        if comment is not None:
            draft.comment = comment
            draft.save(update_fields=["comment"])
    return draft


def approve_results(line: ServiceLine, *, actor: User) -> ResultVersion:
    """Supervisor approval (FEATURES 9.4). The first approval performs the line.

    Raises:
        PermissionDenied: without ``lab.approve_results``.
        DomainError: ``RESULT_NOT_DRAFT``, ``RESULT_INCOMPLETE``.
    """
    require_permission(actor, "lab.approve_results")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="approve results"):
        locked_line = ServiceLine.objects.select_for_update().get(pk=line.pk)
        rs = _result_set(locked_line)
        versions = _versions(rs)
        draft = next((v for v in versions if v.status == ResultStatus.DRAFT), None)
        if draft is None:
            raise DomainError("RESULT_NOT_DRAFT", "There is no draft result to approve")
        expected = set(rs.test.parameters.filter(active=True).values_list("pk", flat=True))
        entered = set(draft.values.values_list("parameter_id", flat=True))
        missing = sorted(expected - entered)
        if missing:
            raise DomainError(
                "RESULT_INCOMPLETE", "Some parameters have no value", parameters=missing
            )
        before = _domain_versions(versions)
        domain_draft = next(v for v in before if v.status is dlab.ResultStatus.DRAFT)
        approved = dlab.approve_version(domain_draft)
        first = dlab.performs_line([v for v in before if v is not domain_draft], approved)
        now = timezone.now()
        if draft.amends_id is not None:
            # At most one approved version: retire the amended one first (same transaction).
            ResultVersion.objects.filter(pk=draft.amends_id, status=ResultStatus.APPROVED).update(
                status=ResultStatus.AMENDED, superseded_at=now, superseded_by=actor
            )
        draft.status = ResultStatus.APPROVED
        draft.approved_by = actor
        draft.approved_at = now
        draft.save(update_fields=["status", "approved_by", "approved_at"])
        if first:
            rs.first_approved_at = now
            rs.save(update_fields=["first_approved_at"])
            _orders().perform_line(locked_line, actor)
        _notify_result(locked_line, draft, amended=draft.amends_id is not None)
    return draft


def _notify_result(line: ServiceLine, version: ResultVersion, *, amended: bool) -> None:
    """Tell the ordering doctor that a result is ready (critical values flagged, 0.13)."""
    critical = [v.parameter.code for v in critical_flags(version)]
    recipients = [line.ordered_by]
    visit_doctor = line.visit.doctor
    if visit_doctor is not None:
        recipients.append(visit_doctor.user)
    kind = "lab_result_critical" if critical else "lab_result_ready"
    notify_users(
        recipients,
        kind,
        service_line_id=line.pk,
        visit_id=line.visit_id,
        version=version.version_no,
        amended=amended,
        critical=critical,
    )


def start_amendment(
    line: ServiceLine, *, actor: User, reason_code: str, note: str = ""
) -> ResultVersion:
    """Correct an approved result: a new draft amending it, values copied (FEATURES 9.5).

    Raises:
        PermissionDenied: without ``lab.amend_results``.
        DomainError: ``RESULT_NOT_APPROVED``, ``AMENDMENT_IN_PROGRESS``, ``REASON_*``.
    """
    require_permission(actor, "lab.amend_results")
    reason = resolve_reason(reason_code, "result_amend", note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"amend result: {note}"):
        locked_line = ServiceLine.objects.select_for_update().get(pk=line.pk)
        rs = _result_set(locked_line)
        versions = _versions(rs)
        approval = Approval(actor.pk, timezone.now(), note, reason.code)
        new = dlab.start_amendment(_domain_versions(versions), approval)
        current = next(v for v in versions if v.status == ResultStatus.APPROVED)
        draft = ResultVersion.objects.create(
            result_set=rs,
            version_no=max(new.number, max(v.version_no for v in versions) + 1),
            amends=current,
            amendment_reason=reason,
            amendment_note=note.strip(),
            comment=current.comment,
            entered_by=actor,
        )
        ResultValue.objects.bulk_create(
            [
                ResultValue(
                    version=draft,
                    parameter_id=v.parameter_id,
                    value_numeric=v.value_numeric,
                    value_text=v.value_text,
                    unit=v.unit,
                    reference_low=v.reference_low,
                    reference_high=v.reference_high,
                    reference_text=v.reference_text,
                    flag=v.flag,
                )
                for v in current.values.all()
            ]
        )
    return draft


def visible_result(line: ServiceLine) -> ResultVersion | None:
    """The approved version doctors and patients see (None until approved)."""
    return (
        ResultVersion.objects.filter(result_set__service_line=line, status=ResultStatus.APPROVED)
        .prefetch_related("values__parameter")
        .first()
    )


def critical_flags(version: ResultVersion) -> list[ResultValue]:
    """Values of a version that need an immediate call to the doctor."""
    critical = {str(dlab.Flag.CRITICAL_LOW), str(dlab.Flag.CRITICAL_HIGH)}
    return [
        v
        for v in version.values.select_related("parameter").order_by("parameter__sort_order")
        if v.flag in critical and dlab.needs_critical_alert([dlab.Flag(v.flag)])
    ]


def cannot_perform(
    line: ServiceLine,
    *,
    actor: User,
    reason_code: str,
    note: str = "",
    approver: User | None = None,
) -> Any:
    """The test cannot be done (sample unusable, analyzer down): cancel the line with a reason;
    the financial engine issues the credit note that makes the payment refundable (9.7),
    approved by ``approver`` (default the actor) holding ``billing.approve_credit_note``.
    """
    reason = resolve_reason(reason_code, "line_cancel", note)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"cannot perform: {note}"):
        _orders().lock_patient(line.visit.patient_id)  # the money engine's lock order
        locked = ServiceLine.objects.select_for_update().get(pk=line.pk)
        _lab_test(locked)
        if ResultVersion.objects.filter(
            result_set__service_line=locked, status=ResultStatus.APPROVED
        ).exists():
            raise DomainError("RESULT_APPROVED_IMMUTABLE", "The test has an approved result")
        return _orders().cancel_line(locked, reason, actor, note=note, approver=approver)


def turnaround_minutes(rs: ResultSet) -> int | None:
    """Minutes from sample receipt (or collection) to first approval (FEATURES 9.8)."""
    if rs.first_approved_at is None or rs.sample is None:
        return None
    start = rs.sample.received_at or rs.sample.collected_at
    return int((rs.first_approved_at - start).total_seconds() // 60)
