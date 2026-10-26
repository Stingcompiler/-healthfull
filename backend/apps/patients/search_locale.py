"""Does the database's locale let ``pg_trgm`` see Arabic letters? (inspection F01)

Fuzzy patient search and duplicate detection (``services.search``, ``find_duplicates``,
the patient import) compare names with ``pg_trgm`` trigrams. ``pg_trgm`` keeps only the
characters the database's ``LC_CTYPE`` calls alphanumeric: under the ``C`` locale every Arabic
letter is a non-alphanumeric, so an Arabic name has no trigrams and every similarity is 0.
Search by exact words still works, but spelling variants are not found and the duplicate
warning never fires for an Arabic name, silently.

The supported locale is a UTF-8 one where Arabic letters are letters, ``en_US.utf8`` (the
official ``postgres:16`` image default, pinned in ``infra/docker-compose.yml`` and in CI).
This module measures it: two Arabic spelling variants must score above
``DUPLICATE_NAME_SIMILARITY``. It is run by ``manage.py check --database default`` (and so by
``migrate``, ``infra/update.sh`` and the first install) and by ``manage.py integrity_check``
(daily, alerting administrators).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Arabic spelling variants beyond what ``hs_normalize_text`` folds; on a database whose locale
#: sees Arabic letters each pair scores about 0.7-0.8, on a ``C`` locale 0.
PROBE_PAIRS: tuple[tuple[str, str], ...] = (
    ("محمد عبدالله احمد", "محمد عبد الله احمد"),
    ("مصطفى عثمان", "مصطفي عثمان"),
)


@dataclass(frozen=True, slots=True)
class Probe:
    left: str
    right: str
    similarity: float


def _threshold() -> float:
    from apps.patients.services import DUPLICATE_NAME_SIMILARITY

    return DUPLICATE_NAME_SIMILARITY


def measure(cursor: Any) -> list[Probe] | None:
    """Similarity of each probe pair on ``cursor``'s database, or None when ``pg_trgm`` is not
    installed there yet (a new database before its first migration)."""
    cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
    if cursor.fetchone() is None:
        return None
    out: list[Probe] = []
    for left, right in PROBE_PAIRS:
        cursor.execute("SELECT similarity(%s, %s)", [left, right])
        (value,) = cursor.fetchone()
        out.append(Probe(left, right, float(value)))
    return out


def locale_of(cursor: Any) -> str:
    cursor.execute(
        "SELECT datctype || ' / ' || datcollate FROM pg_database WHERE datname = current_database()"
    )
    row = cursor.fetchone()
    return str(row[0]) if row else "unknown"


def problems(cursor: Any) -> list[str]:
    """One line per probe pair that scores at or below the duplicate threshold."""
    probes = measure(cursor)
    if probes is None:
        return []
    threshold = _threshold()
    bad = [p for p in probes if p.similarity <= threshold]
    if not bad:
        return []
    where = locale_of(cursor)
    return [
        f"Arabic name similarity is {p.similarity:.2f} for '{p.left}' / '{p.right}' (needs more"
        f" than {threshold}); database LC_CTYPE / LC_COLLATE is {where}. Arabic fuzzy search and"
        " duplicate warnings do not work on this locale: the database must be created with a"
        " UTF-8 locale such as en_US.utf8 (docs/runbooks/install.md, 'Database locale')."
        for p in bad
    ]
