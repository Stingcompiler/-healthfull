"""The restart spec's payment sync point (``apps.core.e2e.pause``) fires exactly where it says
and is never installed by default."""

from __future__ import annotations

from typing import Any

import pghistory
import pytest
from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.e2e import pause
from apps.core.tests import builders as b

pytestmark = pytest.mark.django_db

MIDDLEWARE = "apps.core.e2e.pause.PaymentPauseMiddleware"


class Reached(Exception):
    pass


@pytest.fixture
def reached(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(moment: str) -> None:
        seen.append(moment)
        raise Reached(moment)

    monkeypatch.setattr(pause, "_reached", fake)
    return seen


def _middleware(monkeypatch: pytest.MonkeyPatch, moment: str, view: Any) -> Any:
    monkeypatch.setenv("E2E_PAYMENT_PAUSE", moment)
    return pause.PaymentPauseMiddleware(view)


def test_not_installed_without_the_spec_environment() -> None:
    assert MIDDLEWARE not in settings.MIDDLEWARE


def test_before_commit_stops_right_after_the_payment_insert(
    monkeypatch: pytest.MonkeyPatch, reached: list[str]
) -> None:
    done: list[str] = []

    def view(request: Any) -> HttpResponse:
        # As in a real request: pghistory prefixes the INSERT with its context statement.
        with pghistory.context(user=None, reason="test"):
            b.payment()
        done.append("after insert")
        return HttpResponse(status=201)

    mw = _middleware(monkeypatch, "before_commit", view)
    with pytest.raises(Reached):
        mw(RequestFactory().post(pause.PATH))
    assert reached == ["before_commit"]
    assert done == []  # stopped inside the view, at the INSERT


def test_after_commit_stops_after_a_successful_answer_only(
    monkeypatch: pytest.MonkeyPatch, reached: list[str]
) -> None:
    mw = _middleware(monkeypatch, "after_commit", lambda request: HttpResponse(status=201))
    with pytest.raises(Reached):
        mw(RequestFactory().post(pause.PATH))
    refused = _middleware(monkeypatch, "after_commit", lambda request: HttpResponse(status=409))
    assert refused(RequestFactory().post(pause.PATH)).status_code == 409
    assert reached == ["after_commit"]


def test_other_requests_pass_through(monkeypatch: pytest.MonkeyPatch, reached: list[str]) -> None:
    for moment in pause.MOMENTS:
        mw = _middleware(monkeypatch, moment, lambda request: HttpResponse(status=201))
        assert mw(RequestFactory().get(pause.PATH)).status_code == 201
        assert mw(RequestFactory().post("/api/payments/shifts")).status_code == 201
    assert reached == []
