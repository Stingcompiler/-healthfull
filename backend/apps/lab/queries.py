"""Read services of the lab screens (FEATURES 9.1-9.8).

Each function loads what one screen shows and returns plain dicts shaped like
``apps.lab.schemas``. No rule is decided here: eligibility, stages, reference ranges and
turnaround come from ``apps.lab.services`` and ``domain.lab``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from api.pagination import paginate
from apps.catalog.models import Service, ServiceKind
from apps.core.models import CenterProfile, ReasonCode, User
from apps.lab import services
from apps.lab.models import (
    LabParameter,
    LabTest,
    ReferenceRange,
    ResultFlag,
    ResultSet,
    ResultStatus,
    ResultValue,
    ResultVersion,
    Sample,
    ValueType,
)
from apps.orders.models import FulfilmentStatus, ServiceLine
from apps.patients.models import Patient
from domain import lab as dlab
from domain.errors import DomainError

__all__ = [
    "approvals",
    "label",
    "result_detail",
    "result_print",
    "sample_json",
    "test_detail",
    "tests",
    "turnaround",
    "unlinked_services",
    "worklist",
]

_CRITICAL = {ResultFlag.CRITICAL_LOW.value, ResultFlag.CRITICAL_HIGH.value}
_ABNORMAL = {ResultFlag.LOW.value, ResultFlag.HIGH.value, ResultFlag.ABNORMAL.value}
_DONE_DAYS = 14

# --- small shapes ----------------------------------------------------------------------------


def _dec(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def user_json(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": user.pk,
        "username": user.username,
        "full_name_ar": user.full_name_ar,
        "full_name_en": user.full_name_en,
    }


def reason_json(reason: ReasonCode | None) -> dict[str, Any] | None:
    if reason is None:
        return None
    return {"code": reason.code, "label_ar": reason.label_ar, "label_en": reason.label_en}


def patient_json(p: Patient) -> dict[str, Any]:
    return {
        "id": p.pk,
        "file_no": p.file_no,
        "full_name_ar": p.full_name_ar,
        "full_name_en": p.full_name_en,
        "sex": p.sex,
        "date_of_birth": p.date_of_birth,
    }


def test_ref_json(test: LabTest) -> dict[str, Any]:
    return {
        "id": test.pk,
        "code": test.code,
        "name_ar": test.service.name_ar,
        "name_en": test.service.name_en,
        "sample_type": test.sample_type,
        "container": test.container,
        "turnaround_minutes": test.turnaround_minutes,
    }


def sample_json(sample: Sample) -> dict[str, Any]:
    return {
        "id": sample.pk,
        "accession_no": sample.accession_no,
        "status": sample.status,
        "sample_type": sample.sample_type,
        "collected_at": sample.collected_at,
        "collected_by": user_json(sample.collected_by),
        "received_at": sample.received_at,
        "received_by": user_json(sample.received_by),
        "rejection_reason": reason_json(sample.rejection_reason),
        "rejection_note": sample.rejection_note,
        "label_printed_at": sample.label_printed_at,
    }


def _shown_value(v: ResultValue) -> str:
    if v.value_numeric is None:
        return v.value_text
    places = Decimal(1).scaleb(-v.parameter.decimals)
    return format(v.value_numeric.quantize(places), "f")


def _value_json(v: ResultValue) -> dict[str, Any]:
    return {
        "parameter_id": v.parameter_id,
        "parameter_code": v.parameter.code,
        "name_ar": v.parameter.name_ar,
        "name_en": v.parameter.name_en,
        "value": _shown_value(v),
        "unit": v.unit or v.parameter.unit,
        "reference_low": _dec(v.reference_low),
        "reference_high": _dec(v.reference_high),
        "reference_text": v.reference_text,
        "flag": v.flag,
    }


def _sorted_values(version: ResultVersion) -> list[ResultValue]:
    return sorted(
        version.values.all(), key=lambda v: (v.parameter.sort_order, v.parameter.code, v.pk)
    )


def version_json(version: ResultVersion, by_id: dict[int, int]) -> dict[str, Any]:
    draft = version.status == ResultStatus.DRAFT
    return {
        "id": version.pk,
        "version_no": version.version_no,
        "status": version.status,
        "amends_version_no": by_id.get(version.amends_id) if version.amends_id else None,
        "amendment_reason": reason_json(version.amendment_reason),
        "amendment_note": version.amendment_note,
        "comment": version.comment,
        "entered_by": user_json(version.entered_by),
        "entered_at": version.entered_at,
        "approved_by": user_json(version.approved_by),
        "approved_at": version.approved_at,
        "superseded_at": version.superseded_at,
        "superseded_by": user_json(version.superseded_by),
        "values": [_value_json(v) for v in _sorted_values(version)],
        "revision": services.result_revision(version) if draft else None,
    }


def _authorized(line: ServiceLine) -> bool:
    auth = line.authorization
    return auth is not None and auth.revoked_at is None and line.billing_status != "settled"


# --- work list -------------------------------------------------------------------------------

_VERSIONS = Prefetch(
    "result_set__versions",
    queryset=ResultVersion.objects.prefetch_related("values__parameter").order_by("version_no"),
)


def _rows_qs(qs: QuerySet[ServiceLine]) -> QuerySet[ServiceLine]:
    return qs.filter(service__lab_test__isnull=False).select_related(
        "visit",
        "visit__patient",
        "service",
        "service__lab_test",
        "ordered_by",
        "authorization",
        "result_set",
        "result_set__sample",
        "result_set__sample__collected_by",
        "result_set__sample__received_by",
        "result_set__sample__rejection_reason",
    )


def _search(qs: QuerySet[ServiceLine], q: str | None) -> QuerySet[ServiceLine]:
    term = (q or "").strip()
    if not term:
        return qs
    return qs.filter(
        Q(visit__patient__file_no__icontains=term)
        | Q(visit__patient__full_name_ar__icontains=term)
        | Q(visit__patient__full_name_en__icontains=term)
        | Q(visit__number__icontains=term)
        | Q(result_set__sample__accession_no__icontains=term)
        | Q(service__lab_test__code__iexact=term)
    )


def _expected(tests: Iterable[LabTest]) -> dict[int, int]:
    ids = {t.pk for t in tests}
    counts: dict[int, int] = dict.fromkeys(ids, 0)
    for test_id in LabParameter.objects.filter(test_id__in=ids, active=True).values_list(
        "test_id", flat=True
    ):
        counts[test_id] += 1
    return counts


def _result_set(line: ServiceLine) -> ResultSet | None:
    try:
        return line.result_set
    except ResultSet.DoesNotExist:
        return None


def _row(line: ServiceLine, expected: dict[int, int]) -> tuple[dlab.Stage, dict[str, Any]]:
    test = line.service.lab_test
    rs = _result_set(line)
    versions: list[ResultVersion] = list(rs.versions.all()) if rs is not None else []
    stage = services.stage_of(line, rs, versions, expected.get(test.pk, 0))
    sample = rs.sample if rs is not None else None
    current = next((v for v in versions if v.status == ResultStatus.DRAFT), None) or next(
        (v for v in reversed(versions) if v.status == ResultStatus.APPROVED), None
    )
    critical = current is not None and any(v.flag in _CRITICAL for v in current.values.all())
    due = None
    if sample is not None and sample.status != "rejected":
        start = sample.received_at or sample.collected_at
        due = start + timedelta(minutes=test.turnaround_minutes)
    return stage, {
        "line_id": line.pk,
        "visit_id": line.visit_id,
        "visit_number": line.visit.number,
        "patient": patient_json(line.visit.patient),
        "test": test_ref_json(test),
        "stage": str(stage),
        "ordered_at": line.ordered_at,
        "ordered_by": user_json(line.ordered_by),
        "authorized": _authorized(line),
        "sample": sample_json(sample) if sample is not None else None,
        "critical": critical,
        "due_at": due,
        "approved_at": rs.first_approved_at if rs is not None else None,
    }


def worklist(*, status: str, q: str | None, page: int, page_size: int) -> dict[str, Any]:
    """The bench: paid or authorized open tests by stage, or recently approved ones (9.2)."""
    open_qs = _search(_rows_qs(services.worklist()), q).prefetch_related(_VERSIONS)
    lines = list(open_qs)
    expected = _expected(ln.service.lab_test for ln in lines)
    staged = [_row(line, expected) for line in lines]
    counts = dict.fromkeys(("to_collect", "to_receive", "to_enter", "to_approve"), 0)
    for stage, _ in staged:
        if str(stage) in counts:
            counts[str(stage)] += 1
    if status == "done":
        since = timezone.now() - timedelta(days=_DONE_DAYS)
        done_qs = _search(
            _rows_qs(
                ServiceLine.objects.filter(
                    kind=ServiceKind.LAB,
                    fulfilment_status=FulfilmentStatus.PERFORMED,
                    result_set__first_approved_at__gte=since,
                )
            ),
            q,
        ).order_by("-result_set__first_approved_at", "-id")
        result = paginate(done_qs, page, page_size)
        page_lines = list(result["items"])
        ids = [ln.pk for ln in page_lines]
        loaded = {
            ln.pk: ln
            for ln in _rows_qs(ServiceLine.objects.filter(pk__in=ids)).prefetch_related(_VERSIONS)
        }
        done_expected = _expected(ln.service.lab_test for ln in loaded.values())
        result["items"] = [_row(loaded[i], done_expected)[1] for i in ids]
        return {**result, "counts": counts}
    rows = [row for stage, row in staged if status == "open" or str(stage) == status]
    return {**paginate(rows, page, page_size), "counts": counts}


# --- result detail ---------------------------------------------------------------------------


def _lab_line(line_id: int) -> ServiceLine:
    line = (
        ServiceLine.objects.select_related(
            "visit",
            "visit__patient",
            "service",
            "ordered_by",
            "authorization",
            "cancel_reason",
        )
        .filter(pk=line_id)
        .get()
    )
    if line.kind != ServiceKind.LAB:
        raise DomainError("LINE_NOT_LAB", "The line is not a lab test", line_id=line.pk)
    if not LabTest.objects.filter(service_id=line.service_id).exists():
        raise DomainError("LAB_TEST_UNKNOWN", "The service has no lab test", line_id=line.pk)
    return line


def _versions(rs: ResultSet | None) -> list[ResultVersion]:
    if rs is None:
        return []
    return list(
        rs.versions.select_related("entered_by", "approved_by", "superseded_by", "amendment_reason")
        .prefetch_related("values__parameter")
        .order_by("version_no")
    )


def _applied_range(param: LabParameter, row: ReferenceRange | None) -> dict[str, Any] | None:
    normal = row.normal_text if row is not None else ""
    if param.value_type == ValueType.POS_NEG:
        normal = normal or services.NEGATIVE
    if row is None and not normal:
        return None
    return {
        "low": _dec(row.low) if row else None,
        "high": _dec(row.high) if row else None,
        "critical_low": _dec(row.critical_low) if row else None,
        "critical_high": _dec(row.critical_high) if row else None,
        "normal_text": normal,
    }


def _line_json(line: ServiceLine) -> dict[str, Any]:
    return {
        "id": line.pk,
        "visit_id": line.visit_id,
        "visit_number": line.visit.number,
        "fulfilment_status": line.fulfilment_status,
        "billing_status": line.billing_status,
        "authorized": _authorized(line),
        "ordered_at": line.ordered_at,
        "ordered_by": user_json(line.ordered_by),
        "cancel_reason": reason_json(line.cancel_reason),
        "cancel_note": line.cancel_note,
        "cancelled_at": line.cancelled_at,
    }


def _companions(line: ServiceLine, test: LabTest) -> list[dict[str, Any]]:
    """Other tests of the visit that wait for a sample of the same type (one tube for all)."""
    others = _rows_qs(services.worklist(visit=line.visit).exclude(pk=line.pk)).prefetch_related(
        _VERSIONS
    )
    rows = [o for o in others if o.service.lab_test.sample_type == test.sample_type]
    expected = _expected(o.service.lab_test for o in rows)
    return [
        {"line_id": o.pk, "test": test_ref_json(o.service.lab_test)}
        for o in rows
        if _row(o, expected)[0] is dlab.Stage.TO_COLLECT
    ]


def result_detail(line_id: int) -> dict[str, Any]:
    """One test on the bench: sample, parameters with the patient's ranges, every version."""
    line = _lab_line(line_id)
    test = LabTest.objects.select_related("service").get(service_id=line.service_id)
    rs = (
        ResultSet.objects.select_related(
            "sample", "sample__collected_by", "sample__received_by", "sample__rejection_reason"
        )
        .filter(service_line=line)
        .first()
    )
    versions = _versions(rs)
    by_id = {v.pk: v.version_no for v in versions}
    sample = rs.sample if rs is not None else None
    params = list(
        LabParameter.objects.filter(test=test, active=True)
        .prefetch_related("reference_ranges")
        .order_by("sort_order", "code")
    )
    stage = services.stage_of(line, rs, versions, len(params)) if rs else None
    if stage is None:
        stage = dlab.stage(
            sample=None, cancelled=line.fulfilment_status == FulfilmentStatus.CANCELLED
        )
    return {
        "line": _line_json(line),
        "patient": patient_json(line.visit.patient),
        "test": test_ref_json(test),
        "stage": str(stage),
        "sample": sample_json(sample) if sample is not None else None,
        "parameters": [
            {
                "id": p.pk,
                "code": p.code,
                "name_ar": p.name_ar,
                "name_en": p.name_en,
                "unit": p.unit,
                "value_type": p.value_type,
                "choices": list(p.choices or []),
                "decimals": p.decimals,
                "range": _applied_range(p, services.applicable_range(p, line, sample)),
            }
            for p in params
        ],
        "versions": [version_json(v, by_id) for v in versions],
        "companions": _companions(line, test) if stage is dlab.Stage.TO_COLLECT else [],
        "first_approved_at": rs.first_approved_at if rs is not None else None,
    }


# --- label and print -------------------------------------------------------------------------


def label(sample_id: int) -> dict[str, Any]:
    """What the tube label carries (FEATURES 9.2): accession, patient, tests, collection."""
    sample = Sample.objects.select_related(
        "visit", "visit__patient", "collected_by", "received_by", "rejection_reason"
    ).get(pk=sample_id)
    tests = (
        LabTest.objects.filter(result_sets__sample=sample)
        .select_related("service")
        .order_by("sort_order", "code")
        .distinct()
    )
    return {
        "sample": sample_json(sample),
        "patient": patient_json(sample.visit.patient),
        "visit_number": sample.visit.number,
        "tests": [test_ref_json(t) for t in tests],
    }


def _center_json() -> dict[str, Any]:
    c = CenterProfile.load()
    return {"name_ar": c.name_ar, "name_en": c.name_en, "address": c.address, "phone": c.phone}


def result_print(line_id: int, version_id: int | None) -> dict[str, Any]:
    """An approved result (the current one, or an earlier approved version) for A4 printing.

    Raises:
        DomainError: ``RESULT_NOT_APPROVED`` (no approved version, or a draft asked for).
        ResultVersion.DoesNotExist: a version of another line (404).
    """
    line = _lab_line(line_id)
    test = LabTest.objects.select_related("service").get(service_id=line.service_id)
    rs = (
        ResultSet.objects.select_related(
            "sample", "sample__collected_by", "sample__received_by", "sample__rejection_reason"
        )
        .filter(service_line=line)
        .first()
    )
    versions = _versions(rs)
    by_id = {v.pk: v.version_no for v in versions}
    if version_id is None:
        chosen = next((v for v in versions if v.status == ResultStatus.APPROVED), None)
    else:
        chosen = next((v for v in versions if v.pk == version_id), None)
        if chosen is None:
            raise ResultVersion.DoesNotExist("No such version of this test")
    if chosen is None or chosen.status == ResultStatus.DRAFT:
        raise DomainError("RESULT_NOT_APPROVED", "Only an approved result is printed")
    sample = rs.sample if rs is not None else None
    return {
        "center": _center_json(),
        "patient": patient_json(line.visit.patient),
        "visit_number": line.visit.number,
        "test": test_ref_json(test),
        "sample": sample_json(sample) if sample is not None else None,
        "ordered_by": user_json(line.ordered_by),
        "version": version_json(chosen, by_id),
        "current": chosen.status == ResultStatus.APPROVED,
    }


# --- approval queue --------------------------------------------------------------------------


def approvals(*, page: int, page_size: int) -> dict[str, Any]:
    """Complete drafts waiting for a supervisor, first results and amendments (FEATURES 9.4)."""
    drafts = (
        ResultVersion.objects.filter(status=ResultStatus.DRAFT)
        .exclude(result_set__service_line__fulfilment_status=FulfilmentStatus.CANCELLED)
        .select_related(
            "entered_by",
            "amendment_reason",
            "result_set__sample",
            "result_set__test__service",
            "result_set__service_line__visit__patient",
        )
        .prefetch_related("values__parameter")
        .order_by("entered_at", "id")
    )
    drafts_list = list(drafts)
    expected = _expected(v.result_set.test for v in drafts_list)
    rows: list[dict[str, Any]] = []
    for v in drafts_list:
        values = [x for x in v.values.all() if x.parameter.active]
        need = expected.get(v.result_set.test_id, 0)
        if need == 0 or len(values) < need:
            continue
        line = v.result_set.service_line
        sample = v.result_set.sample
        rows.append(
            {
                "line_id": line.pk,
                "version_id": v.pk,
                "version_no": v.version_no,
                "amendment": v.amends_id is not None,
                "amendment_reason": reason_json(v.amendment_reason),
                "patient": patient_json(line.visit.patient),
                "visit_number": line.visit.number,
                "test": test_ref_json(v.result_set.test),
                "accession_no": sample.accession_no if sample is not None else None,
                "entered_by": user_json(v.entered_by),
                "entered_at": v.entered_at,
                "critical_count": sum(1 for x in values if x.flag in _CRITICAL),
                "abnormal_count": sum(1 for x in values if x.flag in _ABNORMAL),
            }
        )
    return paginate(rows, page, page_size)


# --- catalog ---------------------------------------------------------------------------------


def _range_json(r: ReferenceRange) -> dict[str, Any]:
    return {
        "id": r.pk,
        "sex": r.sex,
        "age_min_days": r.age_min_days,
        "age_max_days": r.age_max_days,
        "low": _dec(r.low),
        "high": _dec(r.high),
        "critical_low": _dec(r.critical_low),
        "critical_high": _dec(r.critical_high),
        "normal_text": r.normal_text,
        "note": r.note,
    }


def _service_json(s: Service) -> dict[str, Any]:
    return {"id": s.pk, "code": s.code, "name_ar": s.name_ar, "name_en": s.name_en}


def tests() -> list[dict[str, Any]]:
    """Every lab test of the catalog, active first (FEATURES 9.1)."""
    rows = LabTest.objects.select_related("service").prefetch_related("parameters")
    out = [
        {
            "id": t.pk,
            "code": t.code,
            "name_ar": t.service.name_ar,
            "name_en": t.service.name_en,
            "sample_type": t.sample_type,
            "turnaround_minutes": t.turnaround_minutes,
            "active": t.active,
            "parameter_count": sum(1 for p in t.parameters.all() if p.active),
        }
        for t in rows
    ]
    return sorted(out, key=lambda r: (not r["active"], r["code"]))


def test_detail(test_id: int) -> dict[str, Any]:
    """One test with every parameter (retired ones too) and their reference ranges."""
    t = LabTest.objects.select_related("service").get(pk=test_id)
    params = (
        LabParameter.objects.filter(test=t)
        .prefetch_related("reference_ranges")
        .order_by("-active", "sort_order", "code")
    )
    return {
        "id": t.pk,
        "code": t.code,
        "service": _service_json(t.service),
        "name_ar": t.service.name_ar,
        "name_en": t.service.name_en,
        "sample_type": t.sample_type,
        "container": t.container,
        "method": t.method,
        "turnaround_minutes": t.turnaround_minutes,
        "instructions_ar": t.instructions_ar,
        "instructions_en": t.instructions_en,
        "sort_order": t.sort_order,
        "active": t.active,
        "parameters": [
            {
                "id": p.pk,
                "code": p.code,
                "name_ar": p.name_ar,
                "name_en": p.name_en,
                "unit": p.unit,
                "value_type": p.value_type,
                "choices": list(p.choices or []),
                "decimals": p.decimals,
                "sort_order": p.sort_order,
                "active": p.active,
                "ranges": [_range_json(r) for r in p.reference_ranges.all()],
            }
            for p in params
        ],
    }


def unlinked_services() -> list[dict[str, Any]]:
    """Active lab services of the catalog that have no test set up yet."""
    rows = Service.objects.filter(
        kind=ServiceKind.LAB, active=True, lab_test__isnull=True
    ).order_by("code")
    return [_service_json(s) for s in rows]


# --- turnaround ------------------------------------------------------------------------------


def _stats_json(s: dlab.TurnaroundStats) -> dict[str, Any]:
    return {
        "count": s.count,
        "mean": s.mean,
        "median": s.median,
        "p90": s.p90,
        "maximum": s.maximum,
        "within_target": s.within_target,
        "within_target_percent": s.within_target_percent,
    }


def turnaround(date_from: date | None, date_to: date | None) -> dict[str, Any]:
    """The turnaround report of a period, the last seven days by default (FEATURES 9.8)."""
    end = date_to or timezone.localdate()
    start = date_from or (end - timedelta(days=6))
    report = services.turnaround_report(date_from=start, date_to=end)
    return {
        "date_from": report.date_from,
        "date_to": report.date_to,
        "rows": [
            {
                "test": test_ref_json(r.test),
                "stats": _stats_json(r.stats),
                "open_overdue": r.open_overdue,
            }
            for r in report.rows
        ],
        "total": _stats_json(report.total),
    }
