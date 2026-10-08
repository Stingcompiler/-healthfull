"""Schemas of ``/api/visits`` (ARCHITECTURE 4.11: ``<Thing>In``, ``<Thing>Out``, ``<Thing>Patch``).

Nothing here carries a price: visits, queue rows and appointments are seen by doctors and
nurses too (FEATURES 3.8). Money appears only in the timeline's financial events, which the
router leaves out for users without ``billing.view``. The waiting-room feed carries
abbreviated names only (privacy).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from ninja import Field, Schema

from api.pagination import PageParams
from apps.patients.schemas import PatientBriefOut, UserRefOut

VisitTypeIn = Literal["new", "follow_up", "emergency"]
VisitTypeCode = Literal["new", "follow_up", "emergency", "pharmacy_sale", "inpatient"]
VisitStatusCode = Literal["open", "closed", "cancelled"]
QueueStatusCode = Literal["waiting", "called", "in_progress", "done", "no_show", "cancelled"]
QueueAction = Literal["call", "start", "finish", "no_show", "requeue"]
AppointmentStatusCode = Literal["booked", "arrived", "cancelled", "no_show", "rescheduled"]
LineStateCode = Literal["requested", "invoiced", "paid", "performed", "cancelled"]


def _quantity(value: Decimal) -> str:
    return format(Decimal(value).normalize(), "f")


# --- reference data -------------------------------------------------------------------------


class DepartmentOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class RoomOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


class DoctorOut(Schema):
    id: int
    department_id: int
    name_ar: str
    name_en: str
    specialty_ar: str
    specialty_en: str
    has_consultation_fee: bool

    @staticmethod
    def resolve_name_ar(obj: Any) -> str:
        return str(obj.user.display_name_ar)

    @staticmethod
    def resolve_name_en(obj: Any) -> str:
        return str(obj.user.display_name_en)

    @staticmethod
    def resolve_has_consultation_fee(obj: Any) -> bool:
        return obj.consultation_service_id is not None


class ReasonOut(Schema):
    code: str
    label_ar: str
    label_en: str
    requires_note: bool


class VisitOptionsOut(Schema):
    """What the create-visit form chooses from."""

    departments: list[DepartmentOut]
    doctors: list[DoctorOut]
    cancel_reasons: list[ReasonOut]
    follow_up_window_days: int


class PayerRefOut(Schema):
    id: int
    code: str
    name_ar: str
    name_en: str


# --- visits ---------------------------------------------------------------------------------


class VisitOut(Schema):
    id: int
    number: str
    patient: PatientBriefOut
    visit_type: VisitTypeCode
    status: VisitStatusCode
    department: DepartmentOut | None
    doctor: DoctorOut | None
    payer: PayerRefOut | None = Field(..., description="null = self-pay (cash)")
    card_number: str
    follow_up_of_id: int | None
    appointment_id: int | None
    chief_complaint: str
    created_at: datetime
    created_by: UserRefOut
    closed_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: ReasonOut | None
    cancel_note: str


class LineOut(Schema):
    """A service line of the visit with its display state; never a price."""

    id: int
    service_code: str
    service_name_ar: str
    service_name_en: str
    kind: str
    quantity: str
    order_source: str
    state: LineStateCode
    ordered_at: datetime

    @staticmethod
    def resolve_id(obj: Any) -> int:
        return int(obj.line.pk)

    @staticmethod
    def resolve_service_code(obj: Any) -> str:
        return str(obj.line.service.code)

    @staticmethod
    def resolve_service_name_ar(obj: Any) -> str:
        return str(obj.line.service.name_ar)

    @staticmethod
    def resolve_service_name_en(obj: Any) -> str:
        return str(obj.line.service.name_en)

    @staticmethod
    def resolve_kind(obj: Any) -> str:
        return str(obj.line.kind)

    @staticmethod
    def resolve_quantity(obj: Any) -> str:
        return _quantity(obj.line.quantity)

    @staticmethod
    def resolve_order_source(obj: Any) -> str:
        return str(obj.line.order_source)

    @staticmethod
    def resolve_ordered_at(obj: Any) -> datetime:
        return obj.line.ordered_at


class QueueRowOut(Schema):
    """A token on the reception board."""

    id: int
    visit_id: int
    visit_number: str
    patient: PatientBriefOut
    department: DepartmentOut
    doctor: DoctorOut | None
    room: RoomOut | None
    queue_date: date
    token_no: int
    priority: int
    status: QueueStatusCode
    ready: bool = Field(..., description="Consultation fee paid or authorized (or none due)")
    created_at: datetime
    called_at: datetime | None
    started_at: datetime | None
    done_at: datetime | None

    @staticmethod
    def resolve_visit_number(obj: Any) -> str:
        return str(obj.visit.number)

    @staticmethod
    def resolve_patient(obj: Any) -> Any:
        return obj.visit.patient

    @staticmethod
    def resolve_ready(obj: Any) -> bool:
        return not bool(getattr(obj, "blocked", False))


class VisitDetailOut(Schema):
    visit: VisitOut
    lines: list[LineOut]
    queue_entry: QueueRowOut | None
    queue_ready: bool


class VisitListParams(PageParams):
    patient_id: int | None = Field(None, description="Every visit of the person (merged files)")
    day: date | None = Field(None, description="Visits opened that day")
    department_id: int | None = None
    doctor_id: int | None = None
    status: VisitStatusCode | None = None


class VisitIn(Schema):
    """Open a visit (FEATURES 2.1). The consultation line and queue token are automatic."""

    patient_id: int
    department_id: int | None = None
    doctor_id: int | None = None
    visit_type: VisitTypeIn = "new"
    coverage_id: int | None = Field(None, description="A coverage on file; null = see below")
    use_default_coverage: bool = Field(
        True, description="Without coverage_id: the default coverage on file (false = cash)"
    )
    card_number: str = Field("", max_length=60)
    chief_complaint: str = Field("", max_length=300)


class VisitCancelIn(Schema):
    """Cancel with a ``visit_cancel`` reason code (FEATURES 2.7, invariant 4)."""

    reason_code: str = Field(..., max_length=40)
    note: str = Field("", max_length=500)


class TimelineOut(Schema):
    """One event of the visit timeline (FEATURES 2.4)."""

    at: datetime
    kind: str
    ref_id: int
    actor: UserRefOut | None
    detail: dict[str, Any]

    @staticmethod
    def resolve_at(obj: Any) -> datetime:
        return obj.event.at

    @staticmethod
    def resolve_kind(obj: Any) -> str:
        return str(obj.event.kind)

    @staticmethod
    def resolve_ref_id(obj: Any) -> int:
        return int(obj.event.ref_id)

    @staticmethod
    def resolve_detail(obj: Any) -> dict[str, Any]:
        return dict(obj.event.detail)


# --- queue ----------------------------------------------------------------------------------


class BoardParams(Schema):
    department_id: int | None = None
    doctor_id: int | None = None
    include_finished: bool = False


class CallNextIn(Schema):
    department_id: int
    doctor_id: int | None = None


class QueueMoveIn(Schema):
    action: QueueAction


class DisplayParams(Schema):
    department_id: int | None = None


class DisplayEntryOut(Schema):
    """A token on the waiting-room screen: abbreviated name only."""

    token_no: int
    name_ar: str
    name_en: str
    status: QueueStatusCode
    department: DepartmentOut
    doctor: DoctorOut | None
    room: RoomOut | None
    called_at: datetime | None


class WaitingRoomOut(Schema):
    serving: list[DisplayEntryOut]
    waiting: list[DisplayEntryOut]


class CenterOut(Schema):
    name_ar: str
    name_en: str
    phone: str


class TokenSlipOut(Schema):
    """What the 80 mm token slip prints (FEATURES 2.6)."""

    entry: QueueRowOut
    ahead: int
    center: CenterOut


# --- appointments ---------------------------------------------------------------------------


class AppointmentOut(Schema):
    id: int
    patient: PatientBriefOut | None
    contact_name: str
    contact_phone: str
    doctor: DoctorOut
    department: DepartmentOut
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatusCode
    rescheduled_from_id: int | None
    notes: str
    visit_id: int | None = Field(..., description="The visit opened at check-in")
    cancel_note: str

    @staticmethod
    def resolve_visit_id(obj: Any) -> int | None:
        visit = getattr(obj, "converted_visit", None)
        return None if visit is None else int(visit.pk)


class AgendaItemOut(Schema):
    starts_at: datetime
    ends_at: datetime
    appointment: AppointmentOut | None = Field(..., description="null = a free slot")


class DayAgendaOut(Schema):
    doctor: DoctorOut
    day: date
    works: bool
    items: list[AgendaItemOut]


class AgendaParams(Schema):
    doctor_id: int
    day: date


class UpcomingParams(Schema):
    patient_id: int


class AppointmentIn(Schema):
    doctor_id: int
    starts_at: datetime
    ends_at: datetime | None = Field(None, description="Default: the schedule's slot length")
    patient_id: int | None = None
    contact_name: str = Field("", max_length=200)
    contact_phone: str = Field("", max_length=30)
    notes: str = Field("", max_length=300)


class AppointmentPatch(Schema):
    notes: str | None = Field(None, max_length=300)
    contact_name: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=30)


class RescheduleIn(Schema):
    starts_at: datetime
    ends_at: datetime | None = None


class AppointmentCancelIn(Schema):
    note: str = Field(..., max_length=300)


class CheckInIn(Schema):
    """Open the visit of a booking on arrival (a caller without a file names one)."""

    patient_id: int | None = None
    coverage_id: int | None = None
    use_default_coverage: bool = True
    card_number: str = Field("", max_length=60)
    chief_complaint: str = Field("", max_length=300)
