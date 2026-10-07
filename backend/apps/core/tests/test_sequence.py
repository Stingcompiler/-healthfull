from __future__ import annotations

import threading
from datetime import date

import pytest
from django.db import connection, transaction

from apps.core.models import Sequence
from apps.core.services import next_number
from domain.errors import DomainError
from domain.numbering import parse_document_number


@pytest.mark.django_db
def test_next_number_formats_and_increments() -> None:
    day = date(2026, 3, 1)
    assert next_number("INV", on=day) == "INV-2026-000001"
    assert next_number("INV", on=day) == "INV-2026-000002"
    assert next_number("RCT", on=day) == "RCT-2026-000001"
    assert Sequence.objects.get(code="INV", year=2026).last_value == 2


@pytest.mark.django_db
def test_numbering_restarts_each_year() -> None:
    assert next_number("INV", on=date(2026, 12, 31)) == "INV-2026-000001"
    assert next_number("INV", on=date(2027, 1, 1)) == "INV-2027-000001"
    assert next_number("INV", on=date(2026, 6, 1)) == "INV-2026-000002"


@pytest.mark.django_db
def test_next_number_defaults_to_today() -> None:
    from django.utils import timezone

    number = parse_document_number(next_number("CN"))
    assert number.year == timezone.localdate().year
    assert number.seq == 1


@pytest.mark.django_db
def test_invalid_prefix_is_rejected_before_touching_the_db() -> None:
    with pytest.raises(DomainError) as exc:
        next_number("inv")
    assert exc.value.code == "INVALID_SEQUENCE_PREFIX"
    assert not Sequence.objects.exists()


@pytest.mark.django_db
def test_rolled_back_transaction_does_not_consume_a_number() -> None:
    day = date(2026, 1, 1)

    def create_document_then_fail() -> None:
        with transaction.atomic():
            next_number("INV", on=day)
            raise RuntimeError("document creation failed")

    with pytest.raises(RuntimeError):
        create_document_then_fail()
    assert next_number("INV", on=day) == "INV-2026-000001"


# Transactional tests run after all other DB tests (pytest-django ordering) and flush the
# database when done, which also removes the migration-seeded roles; conftest re-seeds them
# (serialized_rollback is not an option: restoring rows UPDATEs append-only history tables,
# which triggers forbid).
@pytest.mark.django_db(transaction=True)
def test_next_number_refuses_to_run_in_autocommit() -> None:
    assert not connection.in_atomic_block
    with pytest.raises(RuntimeError, match="inside the transaction"):
        next_number("INV", on=date(2026, 2, 2))
    assert not Sequence.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_transactional_tests_still_see_the_migration_seed() -> None:
    """Guards the conftest re-seed: an earlier transactional test flushed every table."""
    from apps.core.models import CenterProfile, Policy, Role
    from apps.core.roles import ROLE_CODES

    assert set(Role.objects.values_list("code", flat=True)) == ROLE_CODES
    assert CenterProfile.objects.filter(pk=1).exists()
    assert Policy.objects.filter(pk=1).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_allocation_is_gap_free_and_unique() -> None:
    day = date(2026, 5, 5)
    workers, per_worker = 6, 15
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    start = threading.Barrier(workers)

    def work() -> None:
        try:
            start.wait()
            for _ in range(per_worker):
                with transaction.atomic():
                    number = next_number("PAY", on=day)
                with lock:
                    results.append(number)
        except BaseException as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=work) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    total = workers * per_worker
    assert len(results) == total
    assert sorted(parse_document_number(n).seq for n in results) == list(range(1, total + 1))
