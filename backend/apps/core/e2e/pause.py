"""A sync point for the restart e2e spec (inspection, restart spec branches).

The spec kills a spawned server while a cash payment is in flight and must hit two moments
on purpose, never by a lucky sleep:

* ``before_commit``: the payment row is inserted, its transaction not committed;
* ``after_commit``: the payment is committed, the answer not yet sent.

With ``E2E_PAYMENT_PAUSE`` set to one of these and ``E2E_SYNC_DIR`` to a directory, the request
``POST /api/payments/payments`` writes ``<dir>/<moment>`` at that moment and then waits (until
the spec SIGKILLs the server). Installed by ``config/settings.py`` only with DEBUG on and an
``e2e_*`` database; never part of a production server.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from django.db import connection
from django.http import HttpRequest, HttpResponse

MOMENTS = ("before_commit", "after_commit")
PATH = "/api/payments/payments"
#: Long enough for any spec to notice the file and kill the server; never reached normally.
WAIT_SECONDS = 600


def _reached(moment: str) -> None:
    sync_dir = Path(os.environ["E2E_SYNC_DIR"])
    sync_dir.mkdir(parents=True, exist_ok=True)
    (sync_dir / moment).write_text(str(os.getpid()))
    time.sleep(WAIT_SECONDS)


class PaymentPauseMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.moment = os.environ.get("E2E_PAYMENT_PAUSE", "")

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method != "POST" or request.path != PATH:
            return self.get_response(request)
        if self.moment == "before_commit":

            def after_insert(
                execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any
            ) -> Any:
                result = execute(sql, params, many, context)
                # Not a prefix: pghistory puts its context statement in front of the SQL.
                if 'INSERT INTO "payments_payment" ' in sql:
                    _reached("before_commit")
                return result

            with connection.execute_wrapper(after_insert):
                return self.get_response(request)
        response = self.get_response(request)
        if self.moment == "after_commit" and 200 <= response.status_code < 300:
            _reached("after_commit")
        return response
