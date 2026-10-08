"""Doctors' weekly clinic hours (FEATURES 13.2): the only writer of ``DoctorSchedule``.

Called by the administration screens (``apps.core.services.set_doctor_schedule``). The rule
(sessions of one weekday never overlap, slot length fits the session) lives in
``domain.schedule``; appointment booking reads the rows (``apps.visits.services``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from typing import Any

import pghistory
from django.db import transaction
from django.db.models import Prefetch

from apps.core.models import DoctorProfile, Room, User
from apps.visits.models import DoctorSchedule
from domain.schedule import WeeklySession, validate_weekly_schedule

__all__ = ["SessionInput", "replace_weekly_schedule", "schedule_prefetch"]


@dataclass(frozen=True, slots=True)
class SessionInput:
    weekday: int
    start: time
    end: time
    slot_minutes: int = 15
    room: Room | None = None


def schedule_prefetch() -> Prefetch[Any]:
    """``prefetch_related`` of a doctor's active weekly sessions, in week order."""
    return Prefetch(
        "schedules",
        queryset=DoctorSchedule.objects.filter(active=True)
        .select_related("room")
        .order_by("weekday", "start_time"),
    )


def replace_weekly_schedule(
    doctor: DoctorProfile, sessions: Sequence[SessionInput], *, actor: User
) -> list[DoctorSchedule]:
    """Replace every session of ``doctor`` with ``sessions`` in one audited transaction.

    Raises:
        DomainError: ``SCHEDULE_*`` from ``domain.schedule.validate_weekly_schedule``.
    """
    validate_weekly_schedule(
        [WeeklySession(s.weekday, s.start, s.end, s.slot_minutes) for s in sessions]
    )
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="weekly schedule"):
        locked = DoctorProfile.objects.select_for_update().get(pk=doctor.pk)
        DoctorSchedule.objects.filter(doctor=locked).delete()
        return [
            DoctorSchedule.objects.create(
                doctor=locked,
                weekday=s.weekday,
                start_time=s.start,
                end_time=s.end,
                slot_minutes=s.slot_minutes,
                room=s.room,
                active=True,
            )
            for s in sorted(sessions, key=lambda s: (s.weekday, s.start))
        ]
