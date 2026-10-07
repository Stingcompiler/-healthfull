"""Pure business rules for hospital-sys.

Nothing in this package may import Django (enforced by ``domain/tests/test_purity.py``).
Functions take and return plain values (Decimal, datetime, dataclasses, enums) and
signal rule violations by raising :class:`domain.errors.DomainError`.
"""
