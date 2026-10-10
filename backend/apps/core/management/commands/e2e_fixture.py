"""``manage.py e2e_fixture <name> --params '<json>' --json``: build e2e test data.

Runs one named builder from ``apps.core.e2e.fixtures`` (or an app's ``e2e_fixtures`` module)
through the services and prints the result as JSON, for the Playwright helpers
(``e2e/helpers/api.ts``) to read ids from::

    manage.py e2e_fixture --list
    manage.py e2e_fixture patient --params '{"payer": "AMAN"}' --json
    manage.py e2e_fixture paid_visit --params '{"doctor": "pediatrician"}'
    echo '{"visit": 12, "items": [{"service": "LAB-CBC"}]}' | manage.py e2e_fixture order \\
        --params - --json

Output: ``{"ok": true, "fixture": <name>, "result": {...}}``. When a rule refuses the data the
command prints ``{"ok": false, "fixture": <name>, "error": {"code", "message", "details"}}``
(the API's error body) on stdout and exits with status 2. With ``--json`` the output is one
ASCII-only line; without it, indented.

Serve mode (the fast path of ``e2e/helpers/api.ts``): ``--serve`` keeps one Django process
and reads one JSON request per line on stdin, answering one JSON line each on stdout, in
order, until stdin closes::

    {"id": 1, "name": "paid_visit", "params": {...}}
      -> {"id": 1, "ok": true, "fixture": "paid_visit", "result": {...}}
    {"id": 2, "batch": [{"name": "patient", "params": {}}, {"name": "visit", ...}]}
      -> {"id": 2, "ok": true, "results": [<one answer per item, as above>]}

Each fixture still runs in its own transaction, exactly as one command run would, so a spec
sees the same data either way; only the process start-up (Python, Django, app imports) is
paid once instead of per call. A batch runs its items in order and stops at the first
refusal (the answers stop there). Anything printed while a fixture runs goes to stderr, so
stdout carries only answers.

Test databases only (``apps.core.e2e.guard``): DEBUG on and an ``e2e_*`` / ``test_*``
database, or ``ALLOW_SEED_E2E=1``.
"""

from __future__ import annotations

import contextlib
import json
import sys
import traceback
from typing import Any, TextIO

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.utils.module_loading import autodiscover_modules

from api.errors import PermissionRequired
from apps.core.e2e import fixtures
from apps.core.e2e.guard import require_test_database
from domain.errors import DomainError


class Command(BaseCommand):
    help = "Build e2e test data through the services and print ids as JSON (test DBs only)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("name", nargs="?", help="Fixture name (see --list).")
        parser.add_argument(
            "--params",
            default="{}",
            help="Parameters as a JSON object; '-' reads them from stdin.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Print one compact ASCII-only JSON line (for scripts).",
        )
        parser.add_argument("--list", action="store_true", help="List the fixtures.")
        parser.add_argument(
            "--serve",
            action="store_true",
            help="Answer JSON requests from stdin, one per line, until stdin closes.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        require_test_database("e2e_fixture")
        autodiscover_modules("e2e_fixtures")
        if options["list"]:
            for spec in sorted(fixtures.REGISTRY.values(), key=lambda f: f.name):
                accepted = ", ".join(sorted(spec.params))
                self.stdout.write(f"{spec.name}: {spec.summary}\n    params: {accepted}")
            return
        if options["serve"]:
            self._serve(sys.stdin)
            return
        name = options["name"]
        if not name:
            raise CommandError("Give a fixture name (or --list).")
        as_json = bool(options["as_json"])
        try:
            params = self._params(str(options["params"]))
            result = fixtures.run_fixture(name, params)
        except DomainError as exc:
            self._emit({"ok": False, "fixture": name, "error": exc.as_dict()}, as_json)
            raise CommandError(
                f"e2e_fixture {name}: {exc.code}: {exc.message}", returncode=2
            ) from exc
        except PermissionRequired as exc:
            error = {
                "code": "PERMISSION_DENIED",
                "message": str(exc),
                "details": {"permission": exc.permission},
            }
            self._emit({"ok": False, "fixture": name, "error": error}, as_json)
            raise CommandError(f"e2e_fixture {name}: {error['message']}", returncode=2) from exc
        self._emit({"ok": True, "fixture": name, "result": result}, as_json)

    # --- serve mode -------------------------------------------------------------------------

    @staticmethod
    def _answer(name: str, params: object) -> dict[str, Any]:
        """One fixture run as a JSON-ready answer (the payload a single run prints)."""
        if not isinstance(params, dict):
            invalid = DomainError("FIXTURE_PARAMS_INVALID", "params must be a JSON object")
            return {"ok": False, "fixture": name, "error": invalid.as_dict()}
        try:
            result = fixtures.run_fixture(name, params)
        except DomainError as exc:
            return {"ok": False, "fixture": name, "error": exc.as_dict()}
        except PermissionRequired as exc:
            error = {
                "code": "PERMISSION_DENIED",
                "message": str(exc),
                "details": {"permission": exc.permission},
            }
            return {"ok": False, "fixture": name, "error": error}
        return {"ok": True, "fixture": name, "result": result}

    def _handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        if "batch" in request:
            items = request["batch"]
            if not isinstance(items, list):
                raise TypeError("batch must be a list")
            results: list[dict[str, Any]] = []
            for item in items:
                answer = self._answer(str(item.get("name", "")), item.get("params", {}))
                results.append(answer)
                if not answer["ok"]:
                    break
            return {"ok": all(r["ok"] for r in results), "results": results}
        return self._answer(str(request.get("name", "")), request.get("params", {}))

    def _serve(self, source: TextIO) -> None:
        for raw in source:
            if not raw.strip():
                continue
            request_id: object = None
            try:
                request = json.loads(raw)
                request_id = request.get("id")
                # A long-lived process: drop a connection the server closed or broke (never
                # inside an outer transaction, such as a test's).
                if not connection.in_atomic_block:
                    connection.close_if_unusable_or_obsolete()
                with contextlib.redirect_stdout(sys.stderr):
                    answer = self._handle_request(request)
            except Exception as exc:
                answer = {
                    "ok": False,
                    "crash": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                }
            answer["id"] = request_id
            # One line per answer (the command's stdout adds the newline), flushed at once.
            self.stdout.write(
                json.dumps(answer, cls=DjangoJSONEncoder, ensure_ascii=True, sort_keys=True)
            )
            self.stdout.flush()

    def _params(self, raw: str) -> dict[str, Any]:
        text = sys.stdin.read() if raw == "-" else raw
        try:
            data = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise DomainError("FIXTURE_PARAMS_INVALID", f"--params is not JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise DomainError("FIXTURE_PARAMS_INVALID", "--params must be a JSON object")
        return data

    def _emit(self, payload: dict[str, Any], as_json: bool) -> None:
        if as_json:
            text = json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=True, sort_keys=True)
        else:
            text = json.dumps(
                payload, cls=DjangoJSONEncoder, ensure_ascii=False, sort_keys=True, indent=2
            )
        self.stdout.write(text)
