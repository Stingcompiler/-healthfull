"""Default reason lists (FEATURES 13.5), seeded by migration ``0007_seed_reason_codes``.

Categories added later are seeded by the migrations named in ``LATER_SEEDS``. The migrations
hold frozen copies of this list; ``apps/core/tests/test_seeds.py`` keeps the
two in sync. ``ensure_reason_codes()`` re-creates missing rows (for transactional tests,
which truncate migration-seeded tables); rows that exist are left untouched, so a center's
edits survive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReasonDef:
    category: str
    code: str
    label_ar: str
    label_en: str
    requires_note: bool = False


REASON_CODES: tuple[ReasonDef, ...] = (
    # Service line cancellation (FEATURES 4.2).
    ReasonDef("line_cancel", "PATIENT_REFUSED", "رفض المريض", "Patient refused"),
    ReasonDef("line_cancel", "DOCTOR_CANCELLED", "ألغاه الطبيب", "Cancelled by the doctor"),
    ReasonDef("line_cancel", "ORDER_ERROR", "خطأ في الطلب", "Ordered in error"),
    ReasonDef("line_cancel", "DUPLICATE_ORDER", "طلب مكرر", "Duplicate order"),
    ReasonDef("line_cancel", "OUT_OF_STOCK", "الصنف غير متوفر", "Out of stock"),
    ReasonDef("line_cancel", "SAMPLE_UNUSABLE", "العينة غير صالحة", "Sample unusable"),
    ReasonDef("line_cancel", "EQUIPMENT_DOWN", "الجهاز معطل", "Equipment out of service"),
    ReasonDef("line_cancel", "OTHER", "سبب آخر", "Other", True),
    # Visit cancellation (FEATURES 2.7).
    ReasonDef("visit_cancel", "PATIENT_LEFT", "غادر المريض", "Patient left"),
    ReasonDef("visit_cancel", "REGISTRATION_ERROR", "خطأ في التسجيل", "Registration error"),
    ReasonDef("visit_cancel", "DOCTOR_UNAVAILABLE", "الطبيب غير متاح", "Doctor unavailable"),
    ReasonDef("visit_cancel", "DUPLICATE_VISIT", "زيارة مكررة", "Duplicate visit"),
    ReasonDef("visit_cancel", "OTHER", "سبب آخر", "Other", True),
    # Discounts and exemptions (FEATURES 5.9).
    ReasonDef("discount", "STAFF", "موظف أو أسرة موظف", "Staff or staff family"),
    ReasonDef("discount", "HARDSHIP", "ظروف مادية", "Financial hardship"),
    ReasonDef("discount", "FOLLOW_UP", "مراجعة", "Follow-up visit"),
    ReasonDef("discount", "MANAGEMENT", "بتوجيه من الإدارة", "Management decision", True),
    ReasonDef("discount", "OTHER", "سبب آخر", "Other", True),
    # Refunds (FEATURES 6.7).
    ReasonDef("refund", "SERVICE_CANCELLED", "خدمة ملغاة", "Service cancelled"),
    ReasonDef("refund", "SERVICE_UNAVAILABLE", "الخدمة غير متاحة", "Service not available"),
    ReasonDef("refund", "BILLING_ERROR", "خطأ في الفوترة", "Billing error"),
    ReasonDef("refund", "OTHER", "سبب آخر", "Other", True),
    # Credit notes (FEATURES 5.11).
    ReasonDef("credit_note", "SERVICE_CANCELLED", "خدمة ملغاة", "Service cancelled"),
    ReasonDef("credit_note", "PRICE_ERROR", "خطأ في السعر", "Price error"),
    ReasonDef("credit_note", "COVERAGE_ERROR", "خطأ في التغطية", "Coverage error"),
    ReasonDef("credit_note", "DUPLICATE_BILLING", "فوترة مكررة", "Billed twice"),
    ReasonDef("credit_note", "OTHER", "سبب آخر", "Other", True),
    # Stock adjustments (FEATURES 8.6).
    ReasonDef("stock_adjust", "DAMAGED", "تالف", "Damaged"),
    ReasonDef("stock_adjust", "EXPIRED", "منتهي الصلاحية", "Expired"),
    ReasonDef("stock_adjust", "LOST", "مفقود", "Lost"),
    ReasonDef("stock_adjust", "COUNT_CORRECTION", "تصحيح جرد", "Count correction"),
    ReasonDef("stock_adjust", "OPENING_BALANCE", "رصيد افتتاحي", "Opening balance"),
    ReasonDef("stock_adjust", "OTHER", "سبب آخر", "Other", True),
    # Shift cash variance (FEATURES 7.2).
    ReasonDef("variance", "COUNTING_ERROR", "خطأ في العد", "Counting error"),
    ReasonDef("variance", "CHANGE_ERROR", "خطأ في الباقي", "Wrong change given"),
    ReasonDef("variance", "UNRECORDED_PAYMENT", "مقبوضات غير مسجلة", "Unrecorded payment"),
    ReasonDef("variance", "UNEXPLAINED", "غير معروف", "Unexplained", True),
    ReasonDef("variance", "OTHER", "سبب آخر", "Other", True),
    # Supervisor overrides (duplicate references, FEFO batch, discount above the limit).
    ReasonDef(
        "override", "DUPLICATE_VERIFIED", "مرجع مكرر تم التحقق منه", "Duplicate reference verified"
    ),
    ReasonDef("override", "BATCH_CHOICE", "اختيار تشغيلة أخرى", "Different batch chosen"),
    ReasonDef("override", "DISCOUNT_ABOVE_LIMIT", "خصم فوق الحد", "Discount above the limit"),
    ReasonDef("override", "OTHER", "سبب آخر", "Other", True),
    # Payer rejections: rebill to the patient or write off (FEATURES 11.5).
    ReasonDef("writeoff", "NOT_COVERED", "غير مشمول بالتغطية", "Not covered"),
    ReasonDef("writeoff", "NO_PRE_APPROVAL", "بلا موافقة مسبقة", "No pre-approval"),
    ReasonDef("writeoff", "COVERAGE_EXPIRED", "التغطية منتهية", "Coverage expired"),
    ReasonDef("writeoff", "SMALL_BALANCE", "مبلغ صغير", "Small balance"),
    ReasonDef("writeoff", "OTHER", "سبب آخر", "Other", True),
    # Perform-first authorizations (FEATURES 4.4).
    ReasonDef("perform_first", "INSURANCE_APPROVED", "موافقة جهة التغطية", "Payer approval"),
    ReasonDef("perform_first", "EMERGENCY", "طوارئ", "Emergency"),
    ReasonDef("perform_first", "CREDIT_ACCOUNT", "حساب آجل معتمد", "Approved credit account"),
    ReasonDef("perform_first", "OTHER", "سبب آخر", "Other", True),
    # Bank transfer rejection (FEATURES 6.3).
    ReasonDef("transfer_reject", "NOT_RECEIVED", "لم يصل المبلغ", "Money not received"),
    ReasonDef("transfer_reject", "WRONG_AMOUNT", "المبلغ مختلف", "Different amount"),
    ReasonDef("transfer_reject", "WRONG_REFERENCE", "المرجع غير صحيح", "Wrong reference"),
    ReasonDef("transfer_reject", "DUPLICATE", "تحويل مكرر", "Duplicate transfer"),
    ReasonDef("transfer_reject", "OTHER", "سبب آخر", "Other", True),
    # Lab result amendment (FEATURES 9.5).
    ReasonDef("result_amend", "ENTRY_ERROR", "خطأ في الإدخال", "Entry error"),
    ReasonDef("result_amend", "REPEATED_TEST", "إعادة الفحص", "Test repeated"),
    ReasonDef("result_amend", "OTHER", "سبب آخر", "Other", True),
    # Lab sample rejection (FEATURES 9.7).
    ReasonDef("sample_reject", "HEMOLYZED", "عينة متحللة", "Hemolyzed"),
    ReasonDef("sample_reject", "CLOTTED", "عينة متجلطة", "Clotted"),
    ReasonDef("sample_reject", "INSUFFICIENT", "كمية غير كافية", "Insufficient volume"),
    ReasonDef("sample_reject", "MISLABELED", "خطأ في الملصق", "Mislabeled"),
    ReasonDef("sample_reject", "OTHER", "سبب آخر", "Other", True),
    # Patient file merge (FEATURES 1.4). Seeded by migration 0009.
    ReasonDef("patient_merge", "DUPLICATE_REGISTRATION", "تسجيل مكرر", "Registered twice"),
    ReasonDef(
        "patient_merge",
        "EMERGENCY_IDENTIFIED",
        "تم التعرف على مريض طوارئ",
        "Emergency file identified",
    ),
    ReasonDef(
        "patient_merge", "SPELLING_VARIANT", "اختلاف في كتابة الاسم", "Name spelled differently"
    ),
    ReasonDef("patient_merge", "OTHER", "سبب آخر", "Other", True),
    # Appointment cancellation (FEATURES 2.5). Seeded by migration 0009.
    ReasonDef("appointment_cancel", "PATIENT_REQUEST", "بطلب من المريض", "Patient asked"),
    ReasonDef("appointment_cancel", "DOCTOR_UNAVAILABLE", "الطبيب غير متاح", "Doctor unavailable"),
    ReasonDef("appointment_cancel", "BOOKED_IN_ERROR", "حجز بالخطأ", "Booked in error"),
    ReasonDef("appointment_cancel", "OTHER", "سبب آخر", "Other", True),
    # Admission made in error (FEATURES 10.5, ADR 0018). Seeded by migration 0012.
    ReasonDef(
        "admission_cancel", "WRONG_PATIENT", "تنويم مريض آخر بالخطأ", "Wrong patient admitted"
    ),
    ReasonDef("admission_cancel", "NOT_ADMITTED", "المريض لم يُنوَّم", "Patient was not admitted"),
    ReasonDef("admission_cancel", "DUPLICATE_ADMISSION", "تنويم مكرر", "Admitted twice"),
    ReasonDef("admission_cancel", "OTHER", "سبب آخر", "Other", True),
    # Dispense returns (FEATURES 8.4, ADR 0018). Seeded by migration 0013.
    ReasonDef("stock_adjust", "PATIENT_RETURNED", "أعاده المريض", "Returned by the patient"),
    ReasonDef("stock_adjust", "DISPENSED_IN_ERROR", "صُرف بالخطأ", "Dispensed in error"),
)

#: Codes added after ``0007_seed_reason_codes``, with the migration that seeds them.
LATER_SEEDS: dict[str, tuple[str, ...]] = {
    "0009_reason_categories_merge_appointment": ("patient_merge", "appointment_cancel"),
    "0012_admission_cancel_reasons": ("admission_cancel",),
    "0013_dispense_return_reasons": ("stock_adjust",),
}


def ensure_reason_codes() -> int:
    """Create missing default reason codes; returns how many were created."""
    from apps.core.models import ReasonCode

    created = 0
    for order, reason in enumerate(REASON_CODES):
        _, was_created = ReasonCode.objects.get_or_create(
            category=reason.category,
            code=reason.code,
            defaults={
                "label_ar": reason.label_ar,
                "label_en": reason.label_en,
                "requires_note": reason.requires_note,
                "sort_order": order,
            },
        )
        created += int(was_created)
    return created
