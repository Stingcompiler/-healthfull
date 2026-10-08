from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.tests import builders as b
from apps.portal.models import PortalAccessCode

pytestmark = pytest.mark.django_db


def _code(**kw: object) -> PortalAccessCode:
    defaults: dict[str, object] = {
        "patient": b.patient(),
        "code_hash": make_password("483921"),
        "expires_at": timezone.now() + timedelta(days=7),
        "created_by": b.user(),
    }
    defaults.update(kw)
    return PortalAccessCode.objects.create(**defaults)


def test_code_is_stored_hashed_and_history_omits_the_hash() -> None:
    from django.apps import apps

    code = _code()
    assert "483921" not in code.code_hash
    assert check_password("483921", code.code_hash)
    event_fields = {f.name for f in apps.get_model("portal", "PortalAccessCodeEvent")._meta.fields}
    assert "code_hash" not in event_fields


def test_attempts_and_expiry_constraints() -> None:
    code = _code()
    b.db_rejects(
        lambda: PortalAccessCode.objects.filter(pk=code.pk).update(failed_attempts=6),
        "portal_code_attempts_within_max",
    )
    with pytest.raises(IntegrityError, match="portal_code_expires_later"), transaction.atomic():
        _code(expires_at=timezone.now() - timedelta(days=1))
