"""``/api/lab``: work list, samples and labels, results, approval and amendments, cancellation,
test catalog and the turnaround report (FEATURES 9.1-9.8).

Routers stay thin (ARCHITECTURE 4.2): authentication, one ``require_perm``, schema in/out and
one call into ``apps.lab.queries`` (reads) or ``apps.lab.bench`` (commands). Rules live in
``domain.lab`` and ``apps.lab.services``. Doctors read approved results through
``/api/clinical``; drafts never leave the lab.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Status
from ninja.errors import AuthenticationError

from api.permissions import require_perm
from api.ping import add_ping
from api.schemas import ERROR_RESPONSES, ErrorOut
from apps.core.models import User
from apps.lab import bench, queries
from apps.lab.schemas import (
    LabAmendIn,
    LabApprovalPageOut,
    LabApproveIn,
    LabCancelIn,
    LabLabelOut,
    LabPageParams,
    LabParameterIn,
    LabParameterPatch,
    LabPrintOut,
    LabPrintParams,
    LabRangeIn,
    LabRejectIn,
    LabResultIn,
    LabResultOut,
    LabSampleIn,
    LabServiceOptionOut,
    LabTatOut,
    LabTatParams,
    LabTestIn,
    LabTestListItemOut,
    LabTestOut,
    LabTestPatch,
    LabWorklistPageOut,
    LabWorklistParams,
)
from apps.payments.approvals import ApproverLogin

lab_router = Router(tags=["lab"])
add_ping(lab_router, "lab")

_READ = {**ERROR_RESPONSES, 404: ErrorOut}


def _user(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # pragma: no cover - the router's auth guarantees a User
        raise AuthenticationError()
    return user


# --- work list and results -------------------------------------------------------------------


@lab_router.get(
    "/worklist",
    response={200: LabWorklistPageOut, **_READ},
    operation_id="lab_list_worklist",
    summary="Paid or authorized lab tests by bench stage, or recently approved ones",
    description="Unpaid tests never show (invariant 1). `counts` gives the open stages.",
)
@require_perm("lab.view_worklist")
def worklist(request: HttpRequest, params: Query[LabWorklistParams]) -> Any:
    return queries.worklist(
        status=params.status, q=params.q, page=params.page, page_size=params.page_size
    )


@lab_router.get(
    "/lines/{line_id}/result",
    response={200: LabResultOut, **_READ},
    operation_id="lab_get_result",
    summary="One test: sample, parameters with the patient's reference ranges, every version",
)
@require_perm("lab.view_worklist")
def get_result(request: HttpRequest, line_id: int) -> Any:
    return queries.result_detail(line_id)


@lab_router.put(
    "/lines/{line_id}/result",
    response={200: LabResultOut, **_READ},
    operation_id="lab_enter_results",
    summary="Enter or correct values (by parameter code) on the draft; flags are computed",
    description="409 SAMPLE_NOT_RECEIVED, LINE_NOT_ELIGIBLE, RESULT_APPROVED_IMMUTABLE, "
    "PARAMETER_UNKNOWN, RESULT_VALUE_INVALID.",
)
@require_perm("lab.enter_results")
def enter_results(request: HttpRequest, line_id: int, payload: LabResultIn) -> Any:
    return bench.enter(
        line_id, actor=_user(request), values=payload.values, comment=payload.comment
    )


@lab_router.post(
    "/lines/{line_id}/result/approve",
    response={200: LabResultOut, **_READ},
    operation_id="lab_approve_results",
    summary="Approve the draft the supervisor read (the first approval performs the test)",
    description="409 RESULT_CHANGED when values changed since `revision`, RESULT_INCOMPLETE, "
    "RESULT_NOT_DRAFT, LINE_CANCELLED, LINE_NOT_ELIGIBLE.",
)
@require_perm("lab.approve_results")
def approve_results(request: HttpRequest, line_id: int, payload: LabApproveIn) -> Any:
    return bench.approve(line_id, actor=_user(request), revision=payload.revision)


@lab_router.post(
    "/lines/{line_id}/result/amend",
    response={200: LabResultOut, **_READ},
    operation_id="lab_amend_results",
    summary="Correct an approved result: a new draft version; the original is kept",
)
@require_perm("lab.amend_results")
def amend_results(request: HttpRequest, line_id: int, payload: LabAmendIn) -> Any:
    return bench.amend(line_id, actor=_user(request), reason=payload.reason, note=payload.note)


@lab_router.get(
    "/lines/{line_id}/result/print",
    response={200: LabPrintOut, **_READ},
    operation_id="lab_get_result_print",
    summary="An approved result with the center header, for A4 printing in Arabic or English",
    description="409 RESULT_NOT_APPROVED: drafts are never printed.",
)
@require_perm("lab.print_results")
def result_print(request: HttpRequest, line_id: int, params: Query[LabPrintParams]) -> Any:
    return queries.result_print(line_id, params.version_id)


@lab_router.post(
    "/lines/{line_id}/cannot-perform",
    response={200: LabResultOut, **_READ},
    operation_id="lab_cancel_test",
    summary="Cancel a test that cannot be performed, with a reason (refund flow for paid tests)",
    description="A billed test needs a billing supervisor's credentials in `approver` "
    "(409 CANCEL_NEEDS_BILLING_APPROVER, APPROVER_INVALID); 409 RESULT_APPROVED_IMMUTABLE.",
)
@require_perm("lab.cancel_test")
def cancel_test(request: HttpRequest, line_id: int, payload: LabCancelIn) -> Any:
    approver = (
        ApproverLogin(request, payload.approver.username, payload.approver.password)
        if payload.approver is not None
        else None
    )
    return bench.cancel_test(
        line_id, actor=_user(request), reason=payload.reason, note=payload.note, approver=approver
    )


@lab_router.get(
    "/approvals",
    response={200: LabApprovalPageOut, **_READ},
    operation_id="lab_list_approvals",
    summary="Complete drafts waiting for a supervisor: first results and amendments",
)
@require_perm("lab.approve_results")
def approvals(request: HttpRequest, params: Query[LabPageParams]) -> Any:
    return queries.approvals(page=params.page, page_size=params.page_size)


# --- samples ---------------------------------------------------------------------------------


@lab_router.post(
    "/samples",
    response={201: LabResultOut, **_READ},
    operation_id="lab_collect_sample",
    summary="One sample for tests of a visit; with `receive` it is received in the lab at once",
    description="Starts the tests (in progress). 409 LINE_NOT_ELIGIBLE, SAMPLE_TYPE_MISMATCH, "
    "SAMPLE_ALREADY_COLLECTED, LINE_NOT_ON_VISIT.",
)
@require_perm("lab.collect_sample")
def collect_sample(request: HttpRequest, payload: LabSampleIn) -> Any:
    return Status(
        201, bench.collect(payload.line_ids, actor=_user(request), receive=payload.receive)
    )


@lab_router.post(
    "/samples/{sample_id}/receive",
    response={200: LabLabelOut, **_READ},
    operation_id="lab_receive_sample",
    summary="A sample collected outside the lab arrived",
)
@require_perm("lab.receive_sample")
def receive_sample(request: HttpRequest, sample_id: int) -> Any:
    return bench.receive(sample_id, actor=_user(request))


@lab_router.post(
    "/samples/{sample_id}/reject",
    response={200: LabLabelOut, **_READ},
    operation_id="lab_reject_sample",
    summary="Reject an unusable sample with a reason; its tests wait for a new sample",
)
@require_perm("lab.receive_sample")
def reject_sample(request: HttpRequest, sample_id: int, payload: LabRejectIn) -> Any:
    return bench.reject(sample_id, actor=_user(request), reason=payload.reason, note=payload.note)


@lab_router.get(
    "/samples/{sample_id}/label",
    response={200: LabLabelOut, **_READ},
    operation_id="lab_get_sample_label",
    summary="What the tube label prints: accession number, patient, tests, collection time",
)
@require_perm("lab.collect_sample")
def sample_label(request: HttpRequest, sample_id: int) -> Any:
    return queries.label(sample_id)


@lab_router.post(
    "/samples/{sample_id}/label-printed",
    response={200: LabLabelOut, **_READ},
    operation_id="lab_mark_label_printed",
    summary="Record that the tube label was printed",
)
@require_perm("lab.collect_sample")
def label_printed(request: HttpRequest, sample_id: int) -> Any:
    return bench.label_printed(sample_id, actor=_user(request))


# --- catalog ---------------------------------------------------------------------------------


@lab_router.get(
    "/tests",
    response={200: list[LabTestListItemOut], **_READ},
    operation_id="lab_list_tests",
    summary="Every lab test of the catalog",
)
@require_perm("lab.manage_tests")
def list_tests(request: HttpRequest) -> Any:
    return queries.tests()


@lab_router.get(
    "/tests/{test_id}",
    response={200: LabTestOut, **_READ},
    operation_id="lab_get_test",
    summary="One test with its parameters and reference ranges",
)
@require_perm("lab.manage_tests")
def get_test(request: HttpRequest, test_id: int) -> Any:
    return queries.test_detail(test_id)


@lab_router.get(
    "/services-available",
    response={200: list[LabServiceOptionOut], **_READ},
    operation_id="lab_list_unlinked_services",
    summary="Active lab services of the catalog that have no test set up yet",
)
@require_perm("lab.manage_tests")
def unlinked_services(request: HttpRequest) -> Any:
    return queries.unlinked_services()


@lab_router.post(
    "/tests",
    response={201: LabTestOut, **_READ},
    operation_id="lab_create_test",
    summary="Set up the test of a lab service (sample, container, turnaround)",
    description="409 SERVICE_NOT_LAB, LAB_TEST_EXISTS.",
)
@require_perm("lab.manage_tests")
def create_test(request: HttpRequest, payload: LabTestIn) -> Any:
    return Status(201, bench.create_test(actor=_user(request), **payload.dict()))


@lab_router.patch(
    "/tests/{test_id}",
    response={200: LabTestOut, **_READ},
    operation_id="lab_update_test",
    summary="Change a test's sample, container, method, turnaround, instructions or status",
)
@require_perm("lab.manage_tests")
def update_test(request: HttpRequest, test_id: int, payload: LabTestPatch) -> Any:
    fields = payload.dict(exclude_unset=True, exclude_none=True)
    return bench.update_test(test_id, actor=_user(request), fields=fields)


@lab_router.post(
    "/tests/{test_id}/parameters",
    response={201: LabTestOut, **_READ},
    operation_id="lab_create_parameter",
    summary="Add a parameter to a test",
    description="409 PARAMETER_EXISTS, PARAMETER_CHOICES_REQUIRED.",
)
@require_perm("lab.manage_tests")
def create_parameter(request: HttpRequest, test_id: int, payload: LabParameterIn) -> Any:
    return Status(201, bench.add_parameter(test_id, actor=_user(request), fields=payload.dict()))


@lab_router.patch(
    "/parameters/{parameter_id}",
    response={200: LabTestOut, **_READ},
    operation_id="lab_update_parameter",
    summary="Rename a parameter, change its unit or entry type, or retire it",
)
@require_perm("lab.manage_tests")
def update_parameter(request: HttpRequest, parameter_id: int, payload: LabParameterPatch) -> Any:
    fields = payload.dict(exclude_unset=True, exclude_none=True)
    return bench.update_parameter(parameter_id, actor=_user(request), fields=fields)


@lab_router.post(
    "/parameters/{parameter_id}/ranges",
    response={201: LabTestOut, **_READ},
    operation_id="lab_create_range",
    summary="Add a reference range (by sex and age, with critical limits)",
    description="409 INVALID_REFERENCE_RANGE.",
)
@require_perm("lab.manage_tests")
def create_range(request: HttpRequest, parameter_id: int, payload: LabRangeIn) -> Any:
    return Status(201, bench.add_range(parameter_id, actor=_user(request), fields=payload.dict()))


@lab_router.put(
    "/ranges/{range_id}",
    response={200: LabTestOut, **_READ},
    operation_id="lab_update_range",
    summary="Replace a reference range; stored results keep the limits they were judged by",
)
@require_perm("lab.manage_tests")
def update_range(request: HttpRequest, range_id: int, payload: LabRangeIn) -> Any:
    return bench.update_range(range_id, actor=_user(request), fields=payload.dict())


@lab_router.delete(
    "/ranges/{range_id}",
    response={200: LabTestOut, **_READ},
    operation_id="lab_delete_range",
    summary="Remove a reference range",
)
@require_perm("lab.manage_tests")
def delete_range(request: HttpRequest, range_id: int) -> Any:
    return bench.delete_range(range_id, actor=_user(request))


# --- reports ---------------------------------------------------------------------------------


@lab_router.get(
    "/reports/turnaround",
    response={200: LabTatOut, **_READ},
    operation_id="lab_get_turnaround_report",
    summary="Turnaround per test: median, 90th percentile, share within target, overdue now",
    description="Defaults to the last seven days. 409 INVALID_DATE_RANGE.",
)
@require_perm("lab.view_reports")
def turnaround(request: HttpRequest, params: Query[LabTatParams]) -> Any:
    return queries.turnaround(params.date_from, params.date_to)
