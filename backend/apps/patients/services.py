"""Patient files: registration, duplicate warning, search, merge, coverage on file.

FEATURES 0.9 and 1.1-1.6. Search and duplicate detection fold Arabic spelling variants with
the database's ``hs_normalize_text`` / ``hs_normalize_phone`` functions (migration
``core.0005``): alef forms (أ إ آ ٱ) to ا, ة to ه, ى/ی to ي, ؤ to و, ئ to ي, tatweel and
diacritics removed, Arabic-Indic digits to 0-9. The generated columns ``search_name``,
``phone_norm`` and ``phone_alt_norm`` hold the folded values with trigram indexes, so a query
folds its term the same way and compares like with like.

Duplicate warning (FEATURES 1.3): same phone (either number), same national ID, or a
similar name (trigram similarity) with the same date of birth. Registration refuses with
``DUPLICATE_PATIENT`` (listing the candidates) unless the receptionist confirms.

Merge (FEATURES 1.4): the source file is never deleted (invoices, payments and journal
lines reference it). It becomes inactive with ``merged_into`` set, a ``PatientMerge`` row
keeps who/why and a snapshot, clinical safety data (allergies, chronic conditions) and
coverage move to the target, and :func:`file_ids` lets history views include merged files.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pghistory
from django.contrib.postgres.search import TrigramSimilarity
from django.db import IntegrityError, connection, transaction
from django.db.models import Prefetch, Q, QuerySet
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.catalog.models import Payer
from apps.core.models import User
from apps.core.services import next_number, require_permission
from apps.patients.models import Patient, PatientCoverage, PatientMerge, Sex
from domain.errors import DomainError

__all__ = [
    "DUPLICATE_NAME_SIMILARITY",
    "MERGE_REASONS",
    "AllergyView",
    "DuplicateCandidate",
    "PatientData",
    "PatientProfile",
    "active_coverage",
    "active_payers",
    "add_coverage",
    "balance",
    "coverages",
    "coverages_valid_on",
    "end_coverage",
    "file_ids",
    "find_duplicates",
    "merge_into",
    "merge_patients",
    "merge_reason",
    "merges",
    "normalize_phone",
    "normalize_text",
    "person_file_ids",
    "profile",
    "register_emergency",
    "register_patient",
    "resolve",
    "search",
    "search_patients",
    "update_coverage",
    "update_patient",
]

#: Trigram similarity of normalized names above which two files look like one person.
DUPLICATE_NAME_SIMILARITY = 0.6
#: Similarity floor for fuzzy name search (spelling variants beyond the folding).
SEARCH_SIMILARITY = 0.3

_FILE_NO_RE = re.compile(r"^[A-Za-z]{1,10}-\d{4}-\d+$")
_ARABIC_RE = re.compile(r"[؀-ۿ]")
_EDITABLE = (
    "full_name_ar",
    "full_name_en",
    "sex",
    "date_of_birth",
    "dob_is_estimated",
    "phone",
    "phone_alt",
    "address",
    "national_id",
    "emergency_contact_name",
    "emergency_contact_phone",
    "notes",
)


@dataclass(frozen=True, slots=True)
class PatientData:
    """Demographics for registration. ``age_years`` estimates a missing date of birth."""

    sex: str
    full_name_ar: str = ""
    full_name_en: str = ""
    date_of_birth: date | None = None
    age_years: int | None = None
    phone: str = ""
    phone_alt: str = ""
    address: str = ""
    national_id: str = ""
    emergency_contact_name: str = ""
    emergency_contact_phone: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    patient: Patient
    reasons: tuple[str, ...]
    similarity: float = 0.0


@dataclass(slots=True)
class _Found:
    patient: Patient
    reasons: list[str] = field(default_factory=list)
    similarity: float = 0.0


# --- normalization ------------------------------------------------------------------------


def _sql_scalar(sql: str, value: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(sql, [value])
        row = cursor.fetchone()
    return str(row[0]) if row and row[0] is not None else ""


def normalize_text(value: str) -> str:
    """Fold Arabic/English text exactly as the stored ``search_name`` is folded."""
    return _sql_scalar("SELECT hs_normalize_text(%s)", value)


def normalize_phone(value: str) -> str:
    """Digits only, Arabic-Indic digits mapped, ``+249``/``00249`` folded to ``0``."""
    return _sql_scalar("SELECT hs_normalize_phone(%s)", value)


# --- validation helpers ---------------------------------------------------------------------


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _require_sex(sex: str, *, allow_unknown: bool) -> None:
    allowed = set(Sex.values) if allow_unknown else {Sex.MALE, Sex.FEMALE}
    if sex not in allowed:
        raise DomainError("INVALID_SEX", "Sex must be male or female", sex=sex)


def _birth_date(data: PatientData, today: date) -> tuple[date | None, bool]:
    if data.date_of_birth is not None:
        if data.date_of_birth > today:
            raise DomainError("INVALID_DATE_OF_BIRTH", "Date of birth is in the future")
        return data.date_of_birth, False
    if data.age_years is not None:
        if isinstance(data.age_years, bool) or not 0 <= data.age_years <= 130:
            raise DomainError("INVALID_AGE", "Age must be between 0 and 130 years")
        try:
            estimated = today.replace(year=today.year - data.age_years)
        except ValueError:  # 29 February
            estimated = today.replace(year=today.year - data.age_years, day=28)
        return estimated, True
    return None, False


def _is_complete(patient: Patient) -> bool:
    """An emergency file is complete once sex, date of birth and a phone are known."""
    return (
        patient.sex in (Sex.MALE, Sex.FEMALE)
        and patient.date_of_birth is not None
        and bool(patient.phone or patient.phone_alt)
    )


# --- duplicates and search ------------------------------------------------------------------


def find_duplicates(
    *,
    full_name_ar: str = "",
    full_name_en: str = "",
    phone: str = "",
    phone_alt: str = "",
    date_of_birth: date | None = None,
    national_id: str = "",
    exclude_id: int | None = None,
    limit: int = 10,
) -> list[DuplicateCandidate]:
    """Active files that may be the same person (FEATURES 1.3), strongest match first.

    Reasons: ``phone`` (either number matches either number), ``national_id``, and
    ``name_dob`` (similar normalized name and the same date of birth).
    """
    found: dict[int, _Found] = {}
    active = Patient.objects.filter(is_active=True, merged_into__isnull=True)
    if exclude_id is not None:
        active = active.exclude(pk=exclude_id)

    phones = {p for p in (normalize_phone(phone), normalize_phone(phone_alt)) if len(p) >= 6}
    if phones:
        for pat in active.filter(Q(phone_norm__in=phones) | Q(phone_alt_norm__in=phones)):
            found.setdefault(pat.pk, _Found(pat)).reasons.append("phone")

    if national_id.strip():
        for pat in active.filter(national_id=national_id.strip()):
            found.setdefault(pat.pk, _Found(pat)).reasons.append("national_id")

    name = normalize_text(f"{full_name_ar} {full_name_en}")
    if name and date_of_birth is not None:
        similar = (
            active.filter(date_of_birth=date_of_birth)
            .annotate(sim=TrigramSimilarity("search_name", name))
            .filter(sim__gte=DUPLICATE_NAME_SIMILARITY)
        )
        for pat in similar:
            entry = found.setdefault(pat.pk, _Found(pat))
            entry.reasons.append("name_dob")
            entry.similarity = float(pat.sim)

    ranked = sorted(found.values(), key=lambda f: (-len(f.reasons), -f.similarity, f.patient.pk))
    return [DuplicateCandidate(f.patient, tuple(f.reasons), f.similarity) for f in ranked[:limit]]


def search(
    query: str = "", *, include_inactive: bool = False, incomplete_only: bool = False
) -> QuerySet[Patient]:
    """Patients matching ``query`` in serving order, for paged lists (FEATURES 0.9, 1.1).

    * No query: every file, newest first (``incomplete_only``: emergency files still to
      complete).
    * A file number (``PT-2026-000123``) matches exactly; a bare number also matches the
      end of file numbers and phone numbers.
    * Names match when every folded word appears in the folded name, or when the whole
      folded name is similar (trigram) for spelling variants beyond the folding.

    Merged (inactive) files are left out unless ``include_inactive``. Each row carries its
    active default coverage in ``default_coverages`` (prefetched, a list of 0 or 1).
    """
    base = Patient.objects.all()
    if not include_inactive:
        base = base.filter(is_active=True)
    if incomplete_only:
        base = base.filter(is_incomplete=True)
    base = base.prefetch_related(
        Prefetch(
            "coverages",
            queryset=PatientCoverage.objects.filter(is_default=True, active=True).select_related(
                "payer"
            ),
            to_attr="default_coverages",
        )
    )
    term = _clean(query)
    if not term:
        return base.order_by("-created_at", "-id")

    if _FILE_NO_RE.match(term):
        return base.filter(file_no__iexact=term).order_by("-created_at", "-id")

    digits = normalize_phone(term)
    letters = re.sub(r"[\d\s+()\-]", "", term)
    if digits and not letters:
        q = Q(file_no__endswith=digits)
        if len(digits) >= 4:
            q |= Q(phone_norm__contains=digits) | Q(phone_alt_norm__contains=digits)
        return base.filter(q).order_by("-created_at", "-id")

    folded = normalize_text(term)
    words = [w for w in folded.split(" ") if w]
    every_word = Q()
    for word in words:
        every_word &= Q(search_name__contains=word)
    return (
        base.annotate(sim=TrigramSimilarity("search_name", folded))
        .filter(every_word | Q(sim__gte=SEARCH_SIMILARITY))
        .order_by("-sim", "-created_at", "-id")
    )


def search_patients(
    query: str, *, limit: int = 25, include_inactive: bool = False
) -> list[Patient]:
    """The first ``limit`` matches of :func:`search` (an empty query finds nothing)."""
    if not _clean(query):
        return []
    return list(search(query, include_inactive=include_inactive)[:limit])


# --- registration ---------------------------------------------------------------------------


def _new_file_no() -> str:
    return next_number("PT")


def _lock_identity(
    name_ar: str, name_en: str, phone: str, phone_alt: str, dob: date | None
) -> None:
    """Transaction-scoped advisory locks on the identity keys the duplicate check matches.

    One lock per normalized phone and one per normalized name with birth date, taken in a
    fixed (sorted) order, so two registrations that could match each other run one after
    the other and the second sees the first file (FEATURES 1.3).
    """
    keys = {f"phone:{p}" for p in (normalize_phone(phone), normalize_phone(phone_alt)) if p}
    name = normalize_text(f"{name_ar} {name_en}")
    if name and dob is not None:
        keys.add(f"name:{name}:{dob.isoformat()}")
    with connection.cursor() as cursor:
        for key in sorted(keys):
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"patient:{key}"])


def register_patient(
    data: PatientData,
    *,
    actor: User,
    confirm_not_duplicate: bool = False,
    today: date | None = None,
) -> Patient:
    """Create a patient file with an automatic file number (FEATURES 1.1, 1.3).

    Raises:
        DomainError: ``NAME_REQUIRED``, ``INVALID_SEX``, ``INVALID_DATE_OF_BIRTH``,
            ``INVALID_AGE``, ``DUPLICATE_PATIENT`` (``details.candidates``: ids and reasons),
            ``NATIONAL_ID_TAKEN``.
    """
    on = today or timezone.localdate()
    name_ar, name_en = _clean(data.full_name_ar), _clean(data.full_name_en)
    if not name_ar and not name_en:
        raise DomainError("NAME_REQUIRED", "A name in Arabic or English is required")
    _require_sex(data.sex, allow_unknown=False)
    dob, estimated = _birth_date(data, on)
    try:
        with transaction.atomic(), pghistory.context(user=actor.pk, reason="register patient"):
            # Registrations of the same person (a double-click, two receptionists) serialize
            # on the person's phone and name+birth date before the duplicate check runs.
            _lock_identity(name_ar, name_en, data.phone, data.phone_alt, dob)
            if not confirm_not_duplicate:
                candidates = find_duplicates(
                    full_name_ar=name_ar,
                    full_name_en=name_en,
                    phone=data.phone,
                    phone_alt=data.phone_alt,
                    date_of_birth=dob,
                    national_id=data.national_id,
                )
                if candidates:
                    raise DomainError(
                        "DUPLICATE_PATIENT",
                        "A similar patient file exists",
                        candidates=[
                            {
                                "id": c.patient.pk,
                                "file_no": c.patient.file_no,
                                "reasons": list(c.reasons),
                            }
                            for c in candidates
                        ],
                    )
            return Patient.objects.create(
                file_no=_new_file_no(),
                full_name_ar=name_ar,
                full_name_en=name_en,
                sex=data.sex,
                date_of_birth=dob,
                dob_is_estimated=estimated,
                phone=data.phone.strip(),
                phone_alt=data.phone_alt.strip(),
                address=data.address.strip(),
                national_id=data.national_id.strip(),
                emergency_contact_name=_clean(data.emergency_contact_name),
                emergency_contact_phone=data.emergency_contact_phone.strip(),
                notes=data.notes,
                created_by=actor,
            )
    except IntegrityError as exc:
        if "patients_patient_national_id_unique" in str(exc):
            raise DomainError("NATIONAL_ID_TAKEN", "Another file has this national ID") from exc
        raise


def register_emergency(
    *,
    name: str,
    sex: str,
    actor: User,
    age_years: int | None = None,
    phone: str = "",
    today: date | None = None,
) -> Patient:
    """Emergency registration with a name and sex only, flagged incomplete (FEATURES 1.2).

    No duplicate check (an emergency is never delayed); the file can be merged later.
    ``sex`` may be ``unknown`` for an unidentified patient.
    """
    clean = _clean(name)
    if not clean:
        raise DomainError("NAME_REQUIRED", "A name (or a placeholder) is required")
    _require_sex(sex, allow_unknown=True)
    on = today or timezone.localdate()
    dob, estimated = _birth_date(PatientData(sex=sex, age_years=age_years), on)
    arabic = bool(_ARABIC_RE.search(clean))
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="emergency registration"):
        return Patient.objects.create(
            file_no=_new_file_no(),
            full_name_ar=clean if arabic else "",
            full_name_en="" if arabic else clean,
            sex=sex,
            date_of_birth=dob,
            dob_is_estimated=estimated,
            phone=phone.strip(),
            is_incomplete=True,
            created_by=actor,
        )


def update_patient(
    patient: Patient, *, actor: User, today: date | None = None, **changes: Any
) -> Patient:
    """Edit demographics (also completes an emergency file). Unknown fields are refused.

    ``is_incomplete`` (emergency registration) clears once the file has a known sex, a date
    of birth and a phone.
    """
    unknown = sorted(set(changes) - set(_EDITABLE) - {"age_years"})
    if unknown:
        raise DomainError("FIELD_NOT_EDITABLE", "These fields cannot be edited", fields=unknown)
    on = today or timezone.localdate()
    dob_given = "date_of_birth" in changes
    new_dob = changes.pop("date_of_birth", None)
    estimated_flag = changes.pop("dob_is_estimated", None)
    age_years = changes.pop("age_years", None)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit patient"):
        locked = Patient.objects.select_for_update().get(pk=patient.pk)
        if locked.merged_into_id is not None:
            raise DomainError("PATIENT_MERGED", "This file was merged into another file")
        for name, value in changes.items():
            setattr(locked, name, _clean(value) if name.startswith("full_name") else value)
        if not (locked.full_name_ar or locked.full_name_en):
            raise DomainError("NAME_REQUIRED", "A name in Arabic or English is required")
        _require_sex(locked.sex, allow_unknown=True)
        if dob_given or age_years is not None:
            dob, estimated = _birth_date(
                PatientData(sex=locked.sex, date_of_birth=new_dob, age_years=age_years), on
            )
            locked.date_of_birth = dob
            locked.dob_is_estimated = estimated if estimated_flag is None else bool(estimated_flag)
        elif estimated_flag is not None:
            locked.dob_is_estimated = bool(estimated_flag)
        if locked.is_incomplete and _is_complete(locked):
            locked.is_incomplete = False
        try:
            with transaction.atomic():
                locked.save()
        except IntegrityError as exc:
            if "patients_patient_national_id_unique" in str(exc):
                raise DomainError("NATIONAL_ID_TAKEN", "Another file has this national ID") from exc
            raise
    locked.refresh_from_db()
    return locked


# --- merge ----------------------------------------------------------------------------------


def resolve(patient: Patient) -> Patient:
    """The surviving file of a merged patient (the patient itself when not merged)."""
    current = Patient.objects.get(pk=patient.pk)  # fresh: a merge may have happened since
    seen = {current.pk}
    while current.merged_into_id is not None:
        current = Patient.objects.get(pk=current.merged_into_id)
        if current.pk in seen:  # pragma: no cover - prevented by merge_patients
            break
        seen.add(current.pk)
    return current


def person_file_ids(patient: Patient | int) -> list[int]:
    """Every file of the person ``patient`` belongs to: the survivor and all merged into it."""
    pk = patient if isinstance(patient, int) else patient.pk
    return file_ids(resolve(Patient.objects.get(pk=pk)))


def file_ids(patient: Patient) -> list[int]:
    """The patient's id plus every file merged into it (for history and balance views)."""
    ids = [patient.pk]
    frontier = [patient.pk]
    while frontier:
        nxt = list(Patient.objects.filter(merged_into_id__in=frontier).values_list("pk", flat=True))
        ids.extend(nxt)
        frontier = nxt
    return ids


def _snapshot(patient: Patient) -> dict[str, Any]:
    data = model_to_dict(patient, fields=["file_no", *_EDITABLE, "is_incomplete"])
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in data.items()}


def merge_patients(
    source: Patient, target: Patient, *, actor: User, reason_note: str
) -> PatientMerge:
    """Merge a duplicate ``source`` file into ``target`` (FEATURES 1.4, supervisor only).

    Raises:
        PermissionDenied: the actor lacks ``patients.merge`` (supervisor permission).
        DomainError: ``REASON_REQUIRED``, ``MERGE_SAME_FILE``, ``PATIENT_MERGED`` (either
            file already merged away).
    """
    require_permission(actor, "patients.merge")
    note = reason_note.strip()
    if not note:
        raise DomainError("REASON_REQUIRED", "A merge needs a reason")
    if source.pk == target.pk:
        raise DomainError("MERGE_SAME_FILE", "A file cannot be merged into itself")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason=f"merge: {note}"):
        # Files merged into the source first, then the two files (id order): a money lock
        # always takes a file before the file it was merged into (orders.lock_patient).
        list(Patient.objects.select_for_update().filter(merged_into_id=source.pk).order_by("id"))
        locked = {
            p.pk: p
            for p in Patient.objects.select_for_update()
            .filter(pk__in=[source.pk, target.pk])
            .order_by("id")
        }
        src, tgt = locked[source.pk], locked[target.pk]
        if src.merged_into_id is not None or tgt.merged_into_id is not None:
            raise DomainError("PATIENT_MERGED", "One of the files was already merged")
        snapshot = _snapshot(src)

        src.merged_into = tgt
        src.is_active = False
        src.save(update_fields=["merged_into", "is_active", "updated_at"])
        # Earlier merges into the source now point at the survivor (one hop to resolve).
        for earlier in Patient.objects.filter(merged_into=src).exclude(pk=tgt.pk):
            earlier.merged_into = tgt
            earlier.save(update_fields=["merged_into", "updated_at"])

        # Fill gaps on the surviving file from the duplicate.
        for name in ("full_name_ar", "full_name_en", "phone", "address", "national_id"):
            if not getattr(tgt, name) and getattr(src, name):
                setattr(tgt, name, getattr(src, name))
        if not tgt.phone_alt and src.phone and src.phone != tgt.phone:
            tgt.phone_alt = src.phone
        if tgt.date_of_birth is None and src.date_of_birth is not None:
            tgt.date_of_birth = src.date_of_birth
            tgt.dob_is_estimated = src.dob_is_estimated
        if tgt.sex == Sex.UNKNOWN and src.sex != Sex.UNKNOWN:
            tgt.sex = src.sex
        if tgt.is_incomplete and _is_complete(tgt):
            tgt.is_incomplete = False
        tgt.save()

        # Clinical safety data follows the person (through the clinical app's services).
        importlib.import_module("apps.clinical.services").reassign_patient(src, tgt, actor=actor)
        target_has_default = PatientCoverage.objects.filter(
            patient=tgt, is_default=True, active=True
        ).exists()
        for cov in PatientCoverage.objects.filter(patient=src):
            cov.patient = tgt
            if target_has_default:
                cov.is_default = False
            cov.save(update_fields=["patient", "is_default", "updated_at"])
            target_has_default = target_has_default or (cov.is_default and cov.active)
        importlib.import_module("apps.visits.services").reassign_future_appointments(
            src, tgt, actor=actor
        )

        return PatientMerge.objects.create(
            source=src, target=tgt, reason_note=note, source_snapshot=snapshot, merged_by=actor
        )


# --- coverage on file -----------------------------------------------------------------------


def add_coverage(
    patient: Patient,
    *,
    payer: Payer,
    actor: User,
    card_number: str = "",
    member_name: str = "",
    relation: str = "",
    valid_from: date | None = None,
    valid_to: date | None = None,
    patient_percent_override: Decimal | None = None,
    is_default: bool = True,
) -> PatientCoverage:
    """Record a payer on the patient's file (FEATURES 1.6). A new default replaces the old one.

    Raises:
        DomainError: ``PAYER_INACTIVE``, ``CARD_NUMBER_REQUIRED``, ``INVALID_DATE_RANGE``,
            ``INVALID_PERCENT``, ``PATIENT_MERGED``.
    """
    if not payer.active:
        raise DomainError("PAYER_INACTIVE", "The payer is inactive")
    card = card_number.strip()
    if payer.requires_card_number and not card:
        raise DomainError("CARD_NUMBER_REQUIRED", "This payer requires a card number")
    if valid_from and valid_to and valid_to < valid_from:
        raise DomainError("INVALID_DATE_RANGE", "Coverage ends before it starts")
    if patient_percent_override is not None and not (
        Decimal(0) <= patient_percent_override <= Decimal(100)
    ):
        raise DomainError("INVALID_PERCENT", "Patient percent must be between 0 and 100")
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="coverage on file"):
        locked = Patient.objects.select_for_update().get(pk=patient.pk)
        if locked.merged_into_id is not None:
            raise DomainError("PATIENT_MERGED", "This file was merged into another file")
        if is_default:
            for old in PatientCoverage.objects.filter(patient=locked, is_default=True, active=True):
                old.is_default = False
                old.save(update_fields=["is_default", "updated_at"])
        return PatientCoverage.objects.create(
            patient=locked,
            payer=payer,
            card_number=card,
            member_name=_clean(member_name),
            relation=relation.strip(),
            valid_from=valid_from,
            valid_to=valid_to,
            patient_percent_override=patient_percent_override,
            is_default=is_default,
            created_by=actor,
        )


def end_coverage(coverage: PatientCoverage, *, actor: User) -> PatientCoverage:
    """Deactivate a coverage on file (history keeps it)."""
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="end coverage"):
        locked = PatientCoverage.objects.select_for_update().get(pk=coverage.pk)
        locked.active = False
        locked.is_default = False
        locked.save(update_fields=["active", "is_default", "updated_at"])
    return locked


def active_coverage(
    patient: Patient, *, on: date | None = None, payer: Payer | None = None
) -> PatientCoverage | None:
    """The coverage that applies on ``on``: the default one, or the given payer's."""
    day = on or timezone.localdate()
    qs = PatientCoverage.objects.filter(patient=patient, active=True, payer__active=True).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=day),
        Q(valid_to__isnull=True) | Q(valid_to__gte=day),
    )
    qs = qs.filter(payer=payer) if payer is not None else qs.filter(is_default=True)
    return qs.select_related("payer").order_by("-is_default", "-created_at").first()


def coverages_valid_on(patient: Patient, on: date) -> Sequence[PatientCoverage]:
    """Every active coverage valid on ``on`` (for choosing a payer at visit creation)."""
    return list(
        PatientCoverage.objects.filter(patient=patient, active=True)
        .filter(
            Q(valid_from__isnull=True) | Q(valid_from__lte=on),
            Q(valid_to__isnull=True) | Q(valid_to__gte=on),
        )
        .select_related("payer")
    )


def coverages(patient: Patient, *, include_inactive: bool = False) -> list[PatientCoverage]:
    """The file's coverages, the default first (ended ones only with ``include_inactive``)."""
    qs = PatientCoverage.objects.filter(patient=patient).select_related("payer")
    if not include_inactive:
        qs = qs.filter(active=True)
    return list(qs.order_by("-active", "-is_default", "-created_at", "-id"))


def active_payers() -> QuerySet[Payer]:
    """Payers a coverage can be recorded with (FEATURES 1.6)."""
    return Payer.objects.filter(active=True).order_by("code")


_COVERAGE_EDITABLE = (
    "card_number",
    "member_name",
    "relation",
    "valid_from",
    "valid_to",
    "patient_percent_override",
    "is_default",
)


def update_coverage(coverage: PatientCoverage, *, actor: User, **changes: Any) -> PatientCoverage:
    """Edit a coverage on file (a renewed card, new validity dates, another default).

    The payer never changes: end the coverage and add the new payer instead. Visits keep
    the payer and card they were opened with.

    Raises:
        DomainError: ``FIELD_NOT_EDITABLE``, ``COVERAGE_ENDED``, ``CARD_NUMBER_REQUIRED``,
            ``INVALID_DATE_RANGE``, ``INVALID_PERCENT``, ``PATIENT_MERGED``.
    """
    unknown = sorted(set(changes) - set(_COVERAGE_EDITABLE))
    if unknown:
        raise DomainError("FIELD_NOT_EDITABLE", "These fields cannot be edited", fields=unknown)
    with transaction.atomic(), pghistory.context(user=actor.pk, reason="edit coverage"):
        patient = Patient.objects.select_for_update().get(pk=coverage.patient_id)
        if patient.merged_into_id is not None:
            raise DomainError("PATIENT_MERGED", "This file was merged into another file")
        locked = (
            PatientCoverage.objects.select_for_update().select_related("payer").get(pk=coverage.pk)
        )
        if not locked.active:
            raise DomainError("COVERAGE_ENDED", "This coverage has ended")
        for name, value in changes.items():
            if name in ("card_number", "relation"):
                value = (value or "").strip()
            elif name == "member_name":
                value = _clean(value or "")
            elif name == "is_default":
                value = bool(value)
            setattr(locked, name, value)
        if locked.payer.requires_card_number and not locked.card_number:
            raise DomainError("CARD_NUMBER_REQUIRED", "This payer requires a card number")
        if locked.valid_from and locked.valid_to and locked.valid_to < locked.valid_from:
            raise DomainError("INVALID_DATE_RANGE", "Coverage ends before it starts")
        pct = locked.patient_percent_override
        if pct is not None and not (Decimal(0) <= Decimal(pct) <= Decimal(100)):
            raise DomainError("INVALID_PERCENT", "Patient percent must be between 0 and 100")
        if locked.is_default:
            for old in PatientCoverage.objects.filter(
                patient=patient, is_default=True, active=True
            ).exclude(pk=locked.pk):
                old.is_default = False
                old.save(update_fields=["is_default", "updated_at"])
        locked.save()
    return locked


# --- profile, merge history and balance -----------------------------------------------------

#: Reasons a supervisor gives for merging two files (FEATURES 1.4). Stored at the head of the
#: merge note as ``"<CODE>: <note>"``.
MERGE_REASONS = (
    "DUPLICATE_REGISTRATION",
    "EMERGENCY_IDENTIFIED",
    "SPELLING_VARIANT",
    "OTHER",
)
_MERGE_NOTE_RE = re.compile(r"^([A-Z_]+): (.*)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class AllergyView:
    """An active allergy as the patient card shows it."""

    label_ar: str
    label_en: str
    severity: str


@dataclass(frozen=True, slots=True)
class PatientProfile:
    patient: Patient
    merged_into: Patient | None
    allergies: list[AllergyView]
    default_coverage: PatientCoverage | None


def _allergy_view(allergy: Any) -> AllergyView:
    if allergy.drug_class is not None:
        return AllergyView(allergy.drug_class.name_ar, allergy.drug_class.name_en, allergy.severity)
    if allergy.item is not None:
        name = allergy.item.generic_name
        return AllergyView(name, name, allergy.severity)
    return AllergyView(allergy.substance, allergy.substance, allergy.severity)


def profile(patient: Patient) -> PatientProfile:
    """A file as reception sees it: the file, the file it was merged into, the person's
    active allergies (prominent on the card, FEATURES 3.1) and the default coverage."""
    fresh = Patient.objects.get(pk=patient.pk)
    survivor = resolve(fresh)
    summary = importlib.import_module("apps.clinical.services").patient_summary(survivor)
    return PatientProfile(
        patient=fresh,
        merged_into=survivor if survivor.pk != fresh.pk else None,
        allergies=[_allergy_view(a) for a in summary.allergies],
        default_coverage=active_coverage(fresh),
    )


def merge_into(
    target: Patient, *, duplicate: Patient, actor: User, reason_code: str, note: str
) -> PatientMerge:
    """Merge ``duplicate`` into the surviving file ``target`` with a reason code and note.

    Raises:
        PermissionDenied: the actor lacks ``patients.merge``.
        DomainError: ``REASON_UNKNOWN``, ``REASON_REQUIRED`` and those of
            :func:`merge_patients`.
    """
    require_permission(actor, "patients.merge")
    if reason_code not in MERGE_REASONS:
        raise DomainError(
            "REASON_UNKNOWN",
            "Unknown merge reason",
            category="patient_merge",
            reason_code=reason_code,
        )
    text = note.strip()
    if not text:
        raise DomainError("REASON_REQUIRED", "A merge needs a reason")
    return merge_patients(duplicate, target, actor=actor, reason_note=f"{reason_code}: {text}")


def merge_reason(merge: PatientMerge) -> tuple[str, str]:
    """The reason code and free text of a merge (code ``""`` for a free-text note)."""
    found = _MERGE_NOTE_RE.match(merge.reason_note)
    if found and found.group(1) in MERGE_REASONS:
        return found.group(1), found.group(2)
    return "", merge.reason_note


def merges(patient: Patient) -> list[PatientMerge]:
    """Merges into or out of this file, newest first (the history kept by FEATURES 1.4)."""
    return list(
        PatientMerge.objects.filter(Q(source=patient) | Q(target=patient))
        .select_related("source", "target", "merged_by")
        .order_by("-merged_at", "-id")
    )


def balance(patient: Patient) -> Any:
    """The person's credit, pending transfer money and open invoices (FEATURES 1.5)."""
    return importlib.import_module("apps.payments.services").patient_balance(patient)
