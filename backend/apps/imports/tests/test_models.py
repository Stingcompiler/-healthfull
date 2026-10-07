from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from apps.core.tests import builders as b
from apps.imports.models import ImportJob, ImportRow

pytestmark = pytest.mark.django_db


def test_import_job_rows(settings: object, tmp_path: object) -> None:
    settings.MEDIA_ROOT = str(tmp_path)  # type: ignore[attr-defined]
    job = ImportJob(kind="patients", original_filename="p.xlsx", uploaded_by=b.user())
    job.file.save("p.xlsx", ContentFile(b"x"), save=False)
    job.save()
    ImportRow.objects.create(job=job, row_no=2, status="error", data={"name": ""}, errors=["name"])
    with pytest.raises(IntegrityError, match="imports_row_unique"), transaction.atomic():
        ImportRow.objects.create(job=job, row_no=2, status="valid")
    b.db_rejects(
        lambda: ImportJob.objects.filter(pk=job.pk).update(status="confirmed"),
        "imports_job_confirmation_documented",
    )
    b.db_rejects(
        lambda: ImportJob.objects.filter(pk=job.pk).update(kind="cars"), "imports_job_kind_valid"
    )
