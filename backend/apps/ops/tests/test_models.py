from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.ops.models import BackupRun, RestoreTest

pytestmark = pytest.mark.django_db


def test_backup_and_restore_runs() -> None:
    now = timezone.now()
    run = BackupRun.objects.create(kind="nightly", started_at=now)
    RestoreTest.objects.create(backup=run, started_at=now, status="passed", finished_at=now)
    with pytest.raises(IntegrityError, match="ops_backup_finish_after_start"), transaction.atomic():
        BackupRun.objects.create(
            kind="manual", started_at=now, finished_at=now - timedelta(minutes=1)
        )
    with pytest.raises(IntegrityError, match="ops_backup_status_valid"), transaction.atomic():
        BackupRun.objects.create(kind="manual", started_at=now, status="maybe")
