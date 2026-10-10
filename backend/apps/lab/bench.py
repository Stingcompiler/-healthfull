"""The lab bench's commands (FLOW step 5, FEATURES 9.1-9.7).

Each command runs one ``apps.lab.services`` operation and returns what the screen shows next
(``apps.lab.queries``), so a router makes one call. Rules, locks and audit context stay in
the services; this module only resolves the request's references (the lines of a sample,
a range of a parameter) and the billing supervisor who approves a paid test's cancellation
at the bench (``apps.payments.approvals``, ADR 0009).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from apps.catalog.models import Service
from apps.core.models import User
from apps.core.services import require_permission
from apps.lab import queries, services
from apps.lab.models import LabParameter, LabTest, ReferenceRange, Sample
from apps.orders.models import ServiceLine
from apps.payments.approvals import ApproverLogin, resolve_approver

__all__ = [
    "add_parameter",
    "add_range",
    "amend",
    "approve",
    "cancel_test",
    "collect",
    "create_test",
    "delete_range",
    "enter",
    "label_printed",
    "receive",
    "reject",
    "update_parameter",
    "update_range",
    "update_test",
]


def _line(line_id: int) -> ServiceLine:
    return ServiceLine.objects.select_related("visit").get(pk=line_id)


# --- samples ---------------------------------------------------------------------------------


def collect(line_ids: Sequence[int], *, actor: User, receive: bool) -> dict[str, Any]:
    """One sample for the tests of a visit; drawn in the lab it is received at once (9.2).

    Receiving needs ``lab.receive_sample`` as well (a nurse only collects).
    """
    ids = list(dict.fromkeys(line_ids))
    lines = list(ServiceLine.objects.select_related("visit").filter(pk__in=ids))
    if len(lines) != len(ids):
        raise ServiceLine.DoesNotExist("Unknown service line")
    by_id = {ln.pk: ln for ln in lines}
    ordered = [by_id[i] for i in ids]
    visit = ordered[0].visit
    if receive:
        require_permission(actor, "lab.receive_sample")
        services.collect_and_receive(visit=visit, lines=ordered, actor=actor)
    else:
        services.collect_sample(visit=visit, lines=ordered, actor=actor)
    return queries.result_detail(ordered[0].pk)


def receive(sample_id: int, *, actor: User) -> dict[str, Any]:
    sample = services.receive_sample(Sample.objects.get(pk=sample_id), actor=actor)
    return queries.label(sample.pk)


def reject(sample_id: int, *, actor: User, reason: str, note: str) -> dict[str, Any]:
    """An unusable sample: its tests go back to waiting for a new one."""
    sample = Sample.objects.get(pk=sample_id)
    services.reject_sample(sample, actor=actor, reason_code=reason, note=note)
    return queries.label(sample.pk)


def label_printed(sample_id: int, *, actor: User) -> dict[str, Any]:
    services.mark_label_printed(Sample.objects.get(pk=sample_id), actor=actor)
    return queries.label(sample_id)


# --- results ---------------------------------------------------------------------------------


def enter(
    line_id: int, *, actor: User, values: Mapping[str, str], comment: str | None
) -> dict[str, Any]:
    services.enter_results(_line(line_id), values=values, actor=actor, comment=comment)
    return queries.result_detail(line_id)


def approve(line_id: int, *, actor: User, revision: str) -> dict[str, Any]:
    services.approve_results(_line(line_id), actor=actor, revision=revision)
    return queries.result_detail(line_id)


def amend(line_id: int, *, actor: User, reason: str, note: str) -> dict[str, Any]:
    services.start_amendment(_line(line_id), actor=actor, reason_code=reason, note=note)
    return queries.result_detail(line_id)


def cancel_test(
    line_id: int, *, actor: User, reason: str, note: str, approver: ApproverLogin | None
) -> dict[str, Any]:
    """The test cannot be performed (9.7): cancelled with a reason; a paid test is credited
    with a billing supervisor's approval and its refund request opens at the cashier."""
    chosen = resolve_approver(approver, actor=actor)
    services.cannot_perform(
        _line(line_id), actor=actor, reason_code=reason, note=note, approver=chosen
    )
    return queries.result_detail(line_id)


# --- catalog ---------------------------------------------------------------------------------


def _decimal(value: str | None) -> Decimal | None:
    return None if value is None or value == "" else Decimal(value)


def _range_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for name in ("low", "high", "critical_low", "critical_high"):
        out[name] = _decimal(out.get(name))
    return out


def create_test(*, actor: User, service_id: int, **fields: Any) -> dict[str, Any]:
    service = Service.objects.get(pk=service_id)
    test = services.create_lab_test(service=service, actor=actor, **fields)
    return queries.test_detail(test.pk)


def update_test(test_id: int, *, actor: User, fields: Mapping[str, Any]) -> dict[str, Any]:
    services.update_lab_test(LabTest.objects.get(pk=test_id), actor=actor, **fields)
    return queries.test_detail(test_id)


def add_parameter(test_id: int, *, actor: User, fields: Mapping[str, Any]) -> dict[str, Any]:
    services.add_parameter(LabTest.objects.get(pk=test_id), actor=actor, **fields)
    return queries.test_detail(test_id)


def update_parameter(
    parameter_id: int, *, actor: User, fields: Mapping[str, Any]
) -> dict[str, Any]:
    param = LabParameter.objects.get(pk=parameter_id)
    services.update_parameter(param, actor=actor, **fields)
    return queries.test_detail(param.test_id)


def add_range(parameter_id: int, *, actor: User, fields: Mapping[str, Any]) -> dict[str, Any]:
    param = LabParameter.objects.get(pk=parameter_id)
    services.add_reference_range(param, actor=actor, **_range_fields(fields))
    return queries.test_detail(param.test_id)


def update_range(range_id: int, *, actor: User, fields: Mapping[str, Any]) -> dict[str, Any]:
    rng = ReferenceRange.objects.select_related("parameter").get(pk=range_id)
    services.update_reference_range(rng, actor=actor, **_range_fields(fields))
    return queries.test_detail(rng.parameter.test_id)


def delete_range(range_id: int, *, actor: User) -> dict[str, Any]:
    rng = ReferenceRange.objects.select_related("parameter").get(pk=range_id)
    test_id = rng.parameter.test_id
    services.delete_reference_range(rng, actor=actor)
    return queries.test_detail(test_id)
