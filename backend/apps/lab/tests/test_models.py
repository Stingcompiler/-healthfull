"""Lab results: versioning and approval protections (FEATURES 9.4, 9.5)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.lab.models import (
    LabParameter,
    LabTest,
    ReferenceRange,
    ResultSet,
    ResultValue,
    ResultVersion,
    Sample,
)

pytestmark = pytest.mark.django_db


def _result_set() -> tuple[ResultSet, LabParameter]:
    svc = b.service(kind="lab")
    test = LabTest.objects.create(service=svc, code=f"T{b.n()}", sample_type="serum")
    param = LabParameter.objects.create(
        test=test, code="GLU", name_ar="سكر", name_en="Glucose", unit="mg/dL"
    )
    rs = ResultSet.objects.create(service_line=b.service_line(svc=svc), test=test)
    return rs, param


def _version(rs: ResultSet, param: LabParameter, *, no: int = 1, **extra: Any) -> ResultVersion:
    version = ResultVersion.objects.create(
        result_set=rs, version_no=no, entered_by=b.user(), **extra
    )
    ResultValue.objects.create(
        version=version, parameter=param, value_numeric=Decimal("95"), flag="normal"
    )
    return version


def _approve(version: ResultVersion) -> None:
    ResultVersion.objects.filter(pk=version.pk).update(
        status="approved", approved_by=b.user(), approved_at=timezone.now()
    )


def test_draft_version_and_values_are_editable() -> None:
    rs, param = _result_set()
    version = _version(rs, param)
    ResultVersion.objects.filter(pk=version.pk).update(comment="fasting")
    ResultValue.objects.filter(version=version).update(value_numeric=Decimal("101"))


def test_approved_version_rejects_orm_and_raw_sql() -> None:
    rs, param = _result_set()
    version = _version(rs, param)
    _approve(version)
    b.db_rejects(
        lambda: ResultVersion.objects.filter(pk=version.pk).update(comment="changed"),
        "RESULT_FROZEN",
    )
    b.db_rejects(lambda: ResultVersion.objects.filter(pk=version.pk).delete(), "RESULT_FROZEN")
    b.sql_rejects(
        "UPDATE lab_resultversion SET status = 'draft' WHERE id = %s", [version.pk], "RESULT_FROZEN"
    )
    b.sql_rejects("DELETE FROM lab_resultversion WHERE id = %s", [version.pk], "RESULT_FROZEN")


def test_values_of_an_approved_version_never_change() -> None:
    rs, param = _result_set()
    version = _version(rs, param)
    _approve(version)
    value = version.values.get()
    b.db_rejects(
        lambda: ResultValue.objects.filter(pk=value.pk).update(value_numeric=Decimal("1")),
        "RESULT_FROZEN",
    )
    b.sql_rejects("DELETE FROM lab_resultvalue WHERE id = %s", [value.pk], "RESULT_FROZEN")
    other = LabParameter.objects.create(test=rs.test, code="X", name_ar="س", name_en="X", unit="u")
    b.db_rejects(
        lambda: ResultValue.objects.create(version=version, parameter=other, value_text="x"),
        "RESULT_FROZEN",
    )


def test_amendment_supersedes_the_previous_version() -> None:
    rs, param = _result_set()
    v1 = _version(rs, param)
    _approve(v1)
    v2 = _version(rs, param, no=2, amends=v1, amendment_reason=b.reason("result_amend"))
    # The previous version may only be marked amended, with the supersession stamp.
    b.sql_rejects(
        "UPDATE lab_resultversion SET status = 'amended', superseded_at = now(), "
        "superseded_by_id = %s, comment = 'sneaky' WHERE id = %s",
        [b.user().pk, v1.pk],
        "RESULT_FROZEN",
    )
    b.db_rejects(
        lambda: ResultVersion.objects.filter(pk=v1.pk).update(status="amended"),
        "RESULT_FROZEN",
    )
    ResultVersion.objects.filter(pk=v1.pk).update(
        status="amended", superseded_at=timezone.now(), superseded_by=b.user()
    )
    _approve(v2)
    # Amended versions are frozen for good.
    b.sql_rejects(
        "UPDATE lab_resultversion SET status = 'approved' WHERE id = %s", [v1.pk], "RESULT_FROZEN"
    )
    assert list(rs.versions.values_list("version_no", "status")) == [
        (1, "amended"),
        (2, "approved"),
    ]


def test_one_draft_and_one_current_version_per_result_set() -> None:
    rs, param = _result_set()
    _version(rs, param)
    with pytest.raises(IntegrityError, match="lab_version_one_draft"), transaction.atomic():
        _version(rs, param, no=2)


def test_amendment_needs_a_reason_and_approval_an_approver() -> None:
    rs, param = _result_set()
    v1 = _version(rs, param)
    b.db_rejects(
        lambda: ResultVersion.objects.filter(pk=v1.pk).update(status="approved"),
        "lab_version_approval_documented",
    )
    _approve(v1)
    with (
        pytest.raises(IntegrityError, match="lab_version_amendment_has_reason"),
        transaction.atomic(),
    ):
        _version(rs, param, no=2, amends=v1)


def test_reference_range_constraints() -> None:
    _, param = _result_set()
    ReferenceRange.objects.create(parameter=param, low=Decimal("70"), high=Decimal("110"))
    for kw, name in (
        ({"low": Decimal("10"), "high": Decimal("5")}, "lab_range_low_le_high"),
        ({"age_min_days": 30, "age_max_days": 10}, "lab_range_age_order"),
        ({"low": Decimal("70"), "critical_low": Decimal("80")}, "lab_range_critical_low_below_low"),
        ({"sex": "other"}, "lab_range_sex_valid"),
    ):
        with pytest.raises(IntegrityError, match=name), transaction.atomic():
            ReferenceRange.objects.create(parameter=param, **kw)


def test_sample_reception_and_rejection_documented() -> None:
    sample = Sample.objects.create(
        accession_no="LAB-1",
        visit=b.visit(),
        sample_type="serum",
        collected_at=timezone.now(),
        collected_by=b.user(),
    )
    b.db_rejects(
        lambda: Sample.objects.filter(pk=sample.pk).update(status="received"),
        "lab_sample_receipt_documented",
    )
    b.db_rejects(
        lambda: Sample.objects.filter(pk=sample.pk).update(status="rejected"),
        "lab_sample_rejection_has_reason",
    )
    Sample.objects.filter(pk=sample.pk).update(
        status="rejected", rejection_reason=b.reason("sample_reject")
    )
