"""When a person may close a visit («ختم الزيارة», FLOW step 3: the doctor closes the visit).

Closing ends the visit's clinical record: no new orders, notes, diagnoses or vitals
(``VISIT_NOT_OPEN`` there). It changes nothing billed: lines already ordered are still invoiced,
paid, performed and refunded on a closed visit (invariants 1-7 do not depend on it). The system
closes a visit itself at discharge and when an admission made in error is cancelled; these rules
are for a person closing it by hand.
"""

from __future__ import annotations

from domain.errors import DomainError

__all__ = ["check_close"]


def check_close(*, status: str, active_queue_entries: int, open_admission: bool) -> None:
    """Refuse closing a visit that is not open, still in the clinic queue or admitted.

    Raises:
        DomainError: ``VISIT_NOT_OPEN`` (closed or cancelled), ``VISIT_IN_QUEUE`` (the patient
            is still waiting, called or with the doctor: finish the consultation or mark them
            absent first; ``entries`` gives the count), ``VISIT_ADMITTED`` (an open admission:
            the discharge closes the visit).
    """
    if status != "open":
        raise DomainError("VISIT_NOT_OPEN", "Only an open visit can be closed", status=status)
    if active_queue_entries > 0:
        raise DomainError(
            "VISIT_IN_QUEUE",
            "The patient is still in the clinic queue",
            entries=active_queue_entries,
        )
    if open_admission:
        raise DomainError("VISIT_ADMITTED", "An admitted patient's visit closes at discharge")
