"""``manage.py maintenance`` ends idle portal sessions and removes stale portal counters."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.portal.models import PortalSession, PortalThrottle, PortalThrottleScope
from apps.portal.tests.conftest import PortalClient

pytestmark = pytest.mark.django_db


def test_maintenance_ends_idle_sessions_and_drops_stale_counters(
    signed_in: dict[str, PortalClient],
) -> None:
    now = timezone.now()
    idle = PortalSession.objects.order_by("id").first()
    assert idle is not None
    PortalSession.objects.filter(pk=idle.pk).update(
        created_at=now - timedelta(hours=1), last_seen_at=now - timedelta(minutes=30)
    )
    stale = PortalThrottle.objects.create(scope=PortalThrottleScope.IP, key="10.9.9.9", count=2)
    locked = PortalThrottle.objects.create(
        scope=PortalThrottleScope.FILE,
        key="PT-2026-000099",
        count=5,
        locked_until=now + timedelta(minutes=10),
    )
    PortalThrottle.objects.filter(pk__in=[stale.pk, locked.pk]).update(
        updated_at=now - timedelta(days=1)
    )
    out = StringIO()
    call_command("maintenance", stdout=out)
    assert (
        "ended 1 idle portal session(s), removed 1 stale portal throttle row(s)" in out.getvalue()
    )
    idle.refresh_from_db()
    assert idle.end_reason == "expired"
    assert PortalSession.objects.filter(ended_at=None).count() == 1  # the other one is live
    assert set(PortalThrottle.objects.values_list("key", flat=True)) >= {"PT-2026-000099"}
    assert not PortalThrottle.objects.filter(key="10.9.9.9").exists()
