"""System check ``patients.E001``: the database locale must let pg_trgm see Arabic (F01).

Tagged ``database``, so it runs where a database is in play: ``manage.py migrate`` (the first
install and ``infra/update.sh``) and ``manage.py check --database default``. Never on a plain
``manage.py check`` or at import.
"""

from __future__ import annotations

from typing import Any

from django.core.checks import CheckMessage, Error, Tags, register
from django.db import connections


@register(Tags.database)
def check_arabic_similarity(
    app_configs: Any = None, databases: Any = None, **kwargs: Any
) -> list[CheckMessage]:
    from apps.patients import search_locale

    found: list[CheckMessage] = []
    for alias in databases or ():
        with connections[alias].cursor() as cursor:
            for problem in search_locale.problems(cursor):
                found.append(
                    Error(
                        problem,
                        hint=(
                            "Recreate the database (or its cluster) with a UTF-8 locale where"
                            " Arabic letters are letters, e.g. initdb --locale=en_US.utf8; see"
                            " docs/runbooks/install.md."
                        ),
                        id="patients.E001",
                    )
                )
    return found
