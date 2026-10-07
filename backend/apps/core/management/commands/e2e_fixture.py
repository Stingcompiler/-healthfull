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

Test databases only (``apps.core.e2e.guard``): DEBUG on and an ``e2e_*`` / ``test_*``
database, or ``ALLOW_SEED_E2E=1``.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.serializers.json import DjangoJSONEncoder
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

    def handle(self, *args: Any, **options: Any) -> None:
        require_test_database("e2e_fixture")
        autodiscover_modules("e2e_fixtures")
        if options["list"]:
            for spec in sorted(fixtures.REGISTRY.values(), key=lambda f: f.name):
                accepted = ", ".join(sorted(spec.params))
                self.stdout.write(f"{spec.name}: {spec.summary}\n    params: {accepted}")
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
