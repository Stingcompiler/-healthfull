"""Arabic trigram similarity depends on the database locale (inspection F01).

Under ``LC_CTYPE=C`` pg_trgm treats Arabic letters as non-alphanumerics: names have no
trigrams and every similarity is 0, so spelling variants and duplicates are never found. The
check in ``apps.patients.search_locale`` measures this and fails ``migrate`` /
``check --database`` (``patients.E001``) and ``integrity_check`` with a clear message.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from django.db import connection

from apps.ops import integrity
from apps.patients import checks, search_locale
from apps.patients.services import DUPLICATE_NAME_SIMILARITY

pytestmark = pytest.mark.django_db


def test_the_test_database_locale_sees_arabic() -> None:
    with connection.cursor() as cursor:
        probes = search_locale.measure(cursor)
        assert probes is not None
        assert all(p.similarity > DUPLICATE_NAME_SIMILARITY for p in probes), probes
        assert search_locale.problems(cursor) == []


def test_system_check_passes_here_and_reports_a_bad_locale(monkeypatch: Any) -> None:
    assert checks.check_arabic_similarity(databases=["default"]) == []
    assert checks.check_arabic_similarity(databases=None) == []  # plain `manage.py check`
    monkeypatch.setattr(search_locale, "problems", lambda cursor: ["similarity is 0.00"])
    (error,) = checks.check_arabic_similarity(databases=["default"])
    assert error.id == "patients.E001"
    assert "similarity is 0.00" in error.msg
    assert "en_US.utf8" in (error.hint or "")


def test_integrity_check_reports_the_locale() -> None:
    report = integrity.run(["search_locale"])
    assert report.ok
    (result,) = report.results
    assert result.checked == len(search_locale.PROBE_PAIRS)


@pytest.fixture
def c_locale_cursor() -> Iterator[Any]:
    """A cursor on a scratch database created with the C locale, pg_trgm installed."""
    params = connection.get_connection_params()
    params.pop("cursor_factory", None)
    params.pop("context", None)
    base = {k: v for k, v in params.items() if k in {"host", "port", "user", "password"}}
    name = f"{connection.settings_dict['NAME']}_clocale"[:63]
    try:
        admin = psycopg.connect(dbname="postgres", autocommit=True, **base)
    except psycopg.Error as exc:  # pragma: no cover - environment without the postgres db
        pytest.skip(f"cannot reach the postgres database: {exc}")
    with admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        try:
            admin.execute(
                f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING UTF8'
                " LC_COLLATE 'C' LC_CTYPE 'C'"
            )
        except psycopg.errors.InsufficientPrivilege:  # pragma: no cover
            pytest.skip("the test role may not create databases")
        try:
            with psycopg.connect(dbname=name, autocommit=True, **base) as conn:
                conn.execute("CREATE EXTENSION pg_trgm")
                with conn.cursor() as cursor:
                    yield cursor
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


def test_a_c_locale_database_loses_arabic_similarity_and_the_check_says_why(
    c_locale_cursor: Any,
) -> None:
    # The inspection's failure, reproduced: identical Arabic names are not even similar.
    c_locale_cursor.execute("SELECT similarity('فاطمة إبراهيم', 'فاطمة إبراهيم')")
    assert c_locale_cursor.fetchone()[0] == 0
    probes = search_locale.measure(c_locale_cursor)
    assert probes is not None
    assert [p.similarity for p in probes] == [0.0] * len(search_locale.PROBE_PAIRS)
    found = search_locale.problems(c_locale_cursor)
    assert len(found) == len(search_locale.PROBE_PAIRS)
    assert "C / C" in found[0]
    assert "en_US.utf8" in found[0]


def test_no_pg_trgm_yet_is_not_a_finding() -> None:
    class NoExtension:
        def execute(self, sql: str, params: Any = None) -> None:
            self.sql = sql

        def fetchone(self) -> None:
            return None

    assert search_locale.measure(NoExtension()) is None
    assert search_locale.problems(NoExtension()) == []
