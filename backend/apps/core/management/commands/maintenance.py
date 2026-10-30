"""Daily housekeeping: expired sessions and stale login throttle rows (staff and portal).

Sessions live in the database (SESSION_SAVE_EVERY_REQUEST), so expired rows pile up in
``django_session`` and in every backup unless something removes them; the same goes for
``LoginThrottle`` rows whose window or lock has ended. Run once a day (the compose
``maintenance`` service does; see docs/runbooks). Safe to run at any time.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.core.models import LoginThrottle
from apps.portal import guest as guest_services
from apps.portal import services as portal_services
from apps.visits import services as visit_services


class Command(BaseCommand):
    help = "Delete expired sessions and stale login throttle rows."

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()
        sessions, _ = Session.objects.filter(expire_date__lt=now).delete()
        window = timedelta(seconds=int(getattr(settings, "LOGIN_IP_WINDOW_SECONDS", 900)))
        stale = Q(updated_at__lt=now - max(window, timedelta(hours=1))) & (
            Q(locked_until__isnull=True) | Q(locked_until__lt=now)
        )
        throttles, _ = LoginThrottle.objects.filter(stale).delete()
        self.stdout.write(
            f"maintenance: removed {sessions} expired session(s) and "
            f"{throttles} stale login throttle row(s)."
        )
        # The patient portal's own sessions and counters (ADR 0016).
        portal_ended, portal_throttles = portal_services.purge_stale(now)
        self.stdout.write(
            f"maintenance: ended {portal_ended} idle portal session(s), removed "
            f"{portal_throttles} stale portal throttle row(s)."
        )
        # Online booking requests nobody answered in time (ADR 0029 C). Booking already
        # expires a doctor's due requests under the doctor lock; this tidies the rest.
        expired = visit_services.expire_requests(now)
        self.stdout.write(f"maintenance: expired {expired} unanswered online request(s).")
        # Guest booking (ADR 0029 C, F, G): idle guest sessions, idempotent answers past 24 hours,
        # spent challenges, then the retention sweep of old guest names and phones.
        guest_ended, answers, challenges = guest_services.purge_stale(now)
        self.stdout.write(
            f"maintenance: ended {guest_ended} idle guest session(s), removed {answers} stored "
            f"booking answer(s) and {challenges} spent challenge(s)."
        )
        anonymized = guest_services.anonymize_old_guest_bookings(now)
        self.stdout.write(f"maintenance: anonymized {anonymized} old guest booking(s).")
