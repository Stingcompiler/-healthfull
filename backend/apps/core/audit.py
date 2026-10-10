"""The audit trail viewer (FEATURES 0.4; ``core.view_audit``): who changed what, when, why.

Every mutable model is tracked by django-pghistory (ARCHITECTURE 4.9): one append-only event
table per model, each event a full snapshot of the row with its context (user, request id,
reason, URL). This module reads them:

* :func:`audit_models` lists the tracked models (the filter of the screen);
* :func:`audit_events` pages the events across one or every event table, filtered by model,
  user, day range, object id and action, newest first;
* each page row carries what changed: the fields of an insert or delete snapshot, or for an
  update the fields whose value differs from the object's previous event.

Read-only, plain parameterized SQL over the event tables (their names come from the model
registry, never from the request). Secret-looking fields (password hashes, tokens, access
codes) are never shown.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cache
from typing import Any

from django.db import connection
from django.utils import timezone

from apps.core.models import User
from domain.errors import DomainError

__all__ = [
    "ACTIONS",
    "AuditEvent",
    "AuditFilters",
    "AuditModel",
    "audit_events",
    "audit_models",
]

#: pghistory event labels.
ACTIONS: tuple[str, ...] = ("insert", "update", "delete")
_SECRET = re.compile(r"password|secret|token|code_hash|otp|api_key", re.IGNORECASE)
REDACTED = "***"


@dataclass(frozen=True, slots=True)
class AuditModel:
    label: str
    app_label: str
    verbose_name: str
    table: str
    has_object: bool


@cache
def _registry() -> dict[str, AuditModel]:
    import pghistory.core

    found: dict[str, AuditModel] = {}
    for event_model in pghistory.core.event_models():
        tracked: Any = getattr(event_model, "pgh_tracked_model")  # noqa: B009
        label = tracked._meta.label
        if label in found:  # pragma: no cover - one event model per tracked model here
            continue
        field_names = {f.name for f in event_model._meta.fields}
        found[label] = AuditModel(
            label=label,
            app_label=tracked._meta.app_label,
            verbose_name=str(tracked._meta.verbose_name),
            table=event_model._meta.db_table,
            has_object="pgh_obj" in field_names,
        )
    return dict(sorted(found.items()))


def audit_models() -> list[AuditModel]:
    """Every tracked model, by label (``billing.Invoice``)."""
    return list(_registry().values())


@dataclass(frozen=True, slots=True)
class AuditFilters:
    model: str | None = None
    user_id: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    object_id: str | None = None
    action: str | None = None


@dataclass(frozen=True, slots=True)
class AuditChange:
    field: str
    before: Any
    after: Any


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: str
    model: str
    model_name: str
    object_id: str | None
    action: str
    created_at: datetime
    user: User | None
    user_id: int | None
    reason: str
    method: str
    url: str
    request_id: str
    changes: tuple[AuditChange, ...]


def _q(name: str) -> str:
    return connection.ops.quote_name(name)


def _select(model: AuditModel, filters: AuditFilters) -> tuple[str, list[Any]]:
    obj = "e.pgh_obj_id::text" if model.has_object else "NULL::text"
    where: list[str] = []
    params: list[Any] = [model.label]
    tz = timezone.get_current_timezone()
    if filters.date_from is not None:
        where.append("e.pgh_created_at >= %s")
        params.append(datetime.combine(filters.date_from, time.min, tzinfo=tz))
    if filters.date_to is not None:
        where.append("e.pgh_created_at < %s")
        params.append(datetime.combine(filters.date_to + timedelta(days=1), time.min, tzinfo=tz))
    if filters.action:
        where.append("e.pgh_label = %s")
        params.append(filters.action)
    if filters.object_id:
        if not model.has_object:
            where.append("FALSE")
        else:
            where.append("e.pgh_obj_id::text = %s")
            params.append(filters.object_id)
    if filters.user_id is not None:
        where.append("(c.metadata ->> 'user') = %s")
        params.append(str(filters.user_id))
    sql = (
        f"SELECT %s::text AS model, e.pgh_id, e.pgh_created_at, e.pgh_label, {obj} AS obj_id, "  # noqa: S608 - table from the model registry
        f"e.pgh_context_id FROM {_q(model.table)} e "
        "LEFT JOIN pghistory_context c ON c.id = e.pgh_context_id"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    return sql, params


def _check(filters: AuditFilters) -> list[AuditModel]:
    registry = _registry()
    if filters.model is not None and filters.model not in registry:
        raise DomainError(
            "AUDIT_MODEL_UNKNOWN", "This model has no audit trail", model=filters.model
        )
    if filters.action is not None and filters.action not in ACTIONS:
        raise DomainError("AUDIT_ACTION_UNKNOWN", "Unknown audit action", action=filters.action)
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise DomainError("INVALID_DATE_RANGE", "The start date is after the end date")
    return [registry[filters.model]] if filters.model else list(registry.values())


def audit_events(filters: AuditFilters, *, page: int, page_size: int) -> dict[str, Any]:
    """One page of events (newest first) and the total count.

    Raises:
        DomainError: ``AUDIT_MODEL_UNKNOWN``, ``AUDIT_ACTION_UNKNOWN``, ``INVALID_DATE_RANGE``.
    """
    models = _check(filters)
    parts = [_select(m, filters) for m in models]
    union = " UNION ALL ".join(sql for sql, _ in parts)
    params = [p for _, ps in parts for p in ps]
    offset = (page - 1) * page_size
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM ({union}) AS events", params)  # noqa: S608
        count = int(cursor.fetchone()[0])
        rows: list[tuple[Any, ...]] = []
        if offset < count:
            cursor.execute(
                f"SELECT * FROM ({union}) AS events "  # noqa: S608
                "ORDER BY pgh_created_at DESC, pgh_id DESC LIMIT %s OFFSET %s",
                [*params, page_size, offset],
            )
            rows = list(cursor.fetchall())
    return {
        "items": _details(rows),
        "count": count,
        "page": page,
        "page_size": page_size,
    }


def _snapshots(
    model: AuditModel, ids: Sequence[int]
) -> dict[int, tuple[dict[str, Any], dict[str, Any] | None]]:
    previous = (
        f"(SELECT row_to_json(p)::jsonb FROM {_q(model.table)} p "  # noqa: S608 - table from the model registry
        "WHERE p.pgh_obj_id = e.pgh_obj_id AND p.pgh_id < e.pgh_id "
        "ORDER BY p.pgh_id DESC LIMIT 1)"
        if model.has_object
        else "NULL::jsonb"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT e.pgh_id, row_to_json(e)::jsonb, {previous} "  # noqa: S608
            f"FROM {_q(model.table)} e WHERE e.pgh_id = ANY(%s)",
            [list(ids)],
        )
        return {int(pk): (_load(cur), _load(prev) if prev else None) for pk, cur, prev in cursor}


def _load(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    import json

    return dict(json.loads(value))


def _contexts(ids: Iterable[Any]) -> dict[str, dict[str, Any]]:
    wanted = [str(i) for i in ids if i is not None]
    if not wanted:
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id::text, metadata FROM pghistory_context WHERE id::text = ANY(%s)", [wanted]
        )
        return {pk: _load(meta) if meta else {} for pk, meta in cursor}


def _value(name: str, value: Any) -> Any:
    return REDACTED if _SECRET.search(name) and value not in (None, "") else value


def _changes(
    action: str, current: dict[str, Any], before: dict[str, Any] | None
) -> tuple[AuditChange, ...]:
    out: list[AuditChange] = []
    for name in sorted(current):
        if name.startswith("pgh_"):
            continue
        after = current[name]
        if action == "update" and before is not None:
            prior = before.get(name)
            if prior == after:
                continue
            out.append(AuditChange(name, _value(name, prior), _value(name, after)))
        elif action == "delete":
            out.append(AuditChange(name, _value(name, after), None))
        else:
            out.append(AuditChange(name, None, _value(name, after)))
    return tuple(out)


def _details(rows: Sequence[tuple[Any, ...]]) -> list[AuditEvent]:
    registry = _registry()
    by_model: dict[str, list[int]] = defaultdict(list)
    for label, pgh_id, *_ in rows:
        by_model[label].append(int(pgh_id))
    snapshots = {
        (label, pk): snap
        for label, ids in by_model.items()
        for pk, snap in _snapshots(registry[label], ids).items()
    }
    contexts = _contexts(row[5] for row in rows)
    user_ids: set[int] = set()
    for meta in contexts.values():
        uid = meta.get("user")
        if isinstance(uid, int):
            user_ids.add(uid)
    users = {u.pk: u for u in User.objects.filter(pk__in=user_ids)}

    events: list[AuditEvent] = []
    for label, pgh_id, created, action, obj_id, context_id in rows:
        current, before = snapshots.get((label, int(pgh_id)), ({}, None))
        meta = contexts.get(str(context_id), {}) if context_id else {}
        uid = meta.get("user") if isinstance(meta.get("user"), int) else None
        events.append(
            AuditEvent(
                id=f"{label}:{pgh_id}",
                model=label,
                model_name=registry[label].verbose_name,
                object_id=obj_id,
                action=str(action),
                created_at=created,
                user=users.get(uid) if uid is not None else None,
                user_id=uid,
                reason=str(meta.get("reason") or "")[:500],
                method=str(meta.get("method") or ""),
                url=str(meta.get("url") or "")[:300],
                request_id=str(meta.get("request_id") or ""),
                changes=_changes(str(action), current, before),
            )
        )
    return events
