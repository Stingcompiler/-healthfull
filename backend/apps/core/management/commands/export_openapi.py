"""Write the OpenAPI schema as deterministic, pretty JSON (ARCHITECTURE 4.11).

    uv run python manage.py export_openapi --output ../frontend/openapi.json
    uv run python manage.py export_openapi --output ../frontend/openapi.json --check

``--check`` writes nothing and exits non-zero if the file differs (API drift check).
Without ``--output`` the schema is printed to stdout.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


def render_schema() -> str:
    from api.main import api

    schema = api.get_openapi_schema(path_prefix="/api/")
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Export the OpenAPI schema of /api/ as sorted, pretty-printed JSON."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--output", "-o", help="File to write (default: stdout).")
        parser.add_argument(
            "--check",
            action="store_true",
            help="Do not write; fail if the output file is missing or out of date.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        content = render_schema()
        output: str | None = options.get("output")
        if options.get("check"):
            if not output:
                raise CommandError("--check requires --output")
            path = Path(output)
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != content:
                raise CommandError(
                    f"{output} is out of date. Run: manage.py export_openapi --output {output}"
                )
            self.stdout.write(f"{output} is up to date.")
            return
        if not output:
            self.stdout.write(content, ending="")
            return
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace so a concurrent reader never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            Path(tmp).chmod(0o644)
            Path(tmp).replace(path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self.stdout.write(f"Wrote {path}")
