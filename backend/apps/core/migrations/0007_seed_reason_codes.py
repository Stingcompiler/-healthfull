"""Seed the default reason lists (FEATURES 13.5, invariant 4).

A frozen copy of ``apps.core.reason_codes.REASON_CODES``: migrations must not import app code
that can change. ``apps/core/tests/test_seeds.py`` asserts the two match.
Existing rows are left alone so a center's edits survive re-running.
"""

from django.db import migrations

REASON_CODES = [
    ('line_cancel', 'PATIENT_REFUSED', 'رفض المريض', 'Patient refused', False),
    ('line_cancel', 'DOCTOR_CANCELLED', 'ألغاه الطبيب', 'Cancelled by the doctor', False),
    ('line_cancel', 'ORDER_ERROR', 'خطأ في الطلب', 'Ordered in error', False),
    ('line_cancel', 'DUPLICATE_ORDER', 'طلب مكرر', 'Duplicate order', False),
    ('line_cancel', 'OUT_OF_STOCK', 'الصنف غير متوفر', 'Out of stock', False),
    ('line_cancel', 'SAMPLE_UNUSABLE', 'العينة غير صالحة', 'Sample unusable', False),
    ('line_cancel', 'EQUIPMENT_DOWN', 'الجهاز معطل', 'Equipment out of service', False),
    ('line_cancel', 'OTHER', 'سبب آخر', 'Other', True),
    ('visit_cancel', 'PATIENT_LEFT', 'غادر المريض', 'Patient left', False),
    ('visit_cancel', 'REGISTRATION_ERROR', 'خطأ في التسجيل', 'Registration error', False),
    ('visit_cancel', 'DOCTOR_UNAVAILABLE', 'الطبيب غير متاح', 'Doctor unavailable', False),
    ('visit_cancel', 'DUPLICATE_VISIT', 'زيارة مكررة', 'Duplicate visit', False),
    ('visit_cancel', 'OTHER', 'سبب آخر', 'Other', True),
    ('discount', 'STAFF', 'موظف أو أسرة موظف', 'Staff or staff family', False),
    ('discount', 'HARDSHIP', 'ظروف مادية', 'Financial hardship', False),
    ('discount', 'FOLLOW_UP', 'مراجعة', 'Follow-up visit', False),
    ('discount', 'MANAGEMENT', 'بتوجيه من الإدارة', 'Management decision', True),
    ('discount', 'OTHER', 'سبب آخر', 'Other', True),
    ('refund', 'SERVICE_CANCELLED', 'خدمة ملغاة', 'Service cancelled', False),
    ('refund', 'SERVICE_UNAVAILABLE', 'الخدمة غير متاحة', 'Service not available', False),
    ('refund', 'BILLING_ERROR', 'خطأ في الفوترة', 'Billing error', False),
    ('refund', 'OTHER', 'سبب آخر', 'Other', True),
    ('credit_note', 'SERVICE_CANCELLED', 'خدمة ملغاة', 'Service cancelled', False),
    ('credit_note', 'PRICE_ERROR', 'خطأ في السعر', 'Price error', False),
    ('credit_note', 'COVERAGE_ERROR', 'خطأ في التغطية', 'Coverage error', False),
    ('credit_note', 'DUPLICATE_BILLING', 'فوترة مكررة', 'Billed twice', False),
    ('credit_note', 'OTHER', 'سبب آخر', 'Other', True),
    ('stock_adjust', 'DAMAGED', 'تالف', 'Damaged', False),
    ('stock_adjust', 'EXPIRED', 'منتهي الصلاحية', 'Expired', False),
    ('stock_adjust', 'LOST', 'مفقود', 'Lost', False),
    ('stock_adjust', 'COUNT_CORRECTION', 'تصحيح جرد', 'Count correction', False),
    ('stock_adjust', 'OPENING_BALANCE', 'رصيد افتتاحي', 'Opening balance', False),
    ('stock_adjust', 'OTHER', 'سبب آخر', 'Other', True),
    ('variance', 'COUNTING_ERROR', 'خطأ في العد', 'Counting error', False),
    ('variance', 'CHANGE_ERROR', 'خطأ في الباقي', 'Wrong change given', False),
    ('variance', 'UNRECORDED_PAYMENT', 'مقبوضات غير مسجلة', 'Unrecorded payment', False),
    ('variance', 'UNEXPLAINED', 'غير معروف', 'Unexplained', True),
    ('variance', 'OTHER', 'سبب آخر', 'Other', True),
    ('override', 'DUPLICATE_VERIFIED', 'مرجع مكرر تم التحقق منه', 'Duplicate reference verified', False),
    ('override', 'BATCH_CHOICE', 'اختيار تشغيلة أخرى', 'Different batch chosen', False),
    ('override', 'DISCOUNT_ABOVE_LIMIT', 'خصم فوق الحد', 'Discount above the limit', False),
    ('override', 'OTHER', 'سبب آخر', 'Other', True),
    ('writeoff', 'NOT_COVERED', 'غير مشمول بالتغطية', 'Not covered', False),
    ('writeoff', 'NO_PRE_APPROVAL', 'بلا موافقة مسبقة', 'No pre-approval', False),
    ('writeoff', 'COVERAGE_EXPIRED', 'التغطية منتهية', 'Coverage expired', False),
    ('writeoff', 'SMALL_BALANCE', 'مبلغ صغير', 'Small balance', False),
    ('writeoff', 'OTHER', 'سبب آخر', 'Other', True),
    ('perform_first', 'INSURANCE_APPROVED', 'موافقة جهة التغطية', 'Payer approval', False),
    ('perform_first', 'EMERGENCY', 'طوارئ', 'Emergency', False),
    ('perform_first', 'CREDIT_ACCOUNT', 'حساب آجل معتمد', 'Approved credit account', False),
    ('perform_first', 'OTHER', 'سبب آخر', 'Other', True),
    ('transfer_reject', 'NOT_RECEIVED', 'لم يصل المبلغ', 'Money not received', False),
    ('transfer_reject', 'WRONG_AMOUNT', 'المبلغ مختلف', 'Different amount', False),
    ('transfer_reject', 'WRONG_REFERENCE', 'المرجع غير صحيح', 'Wrong reference', False),
    ('transfer_reject', 'DUPLICATE', 'تحويل مكرر', 'Duplicate transfer', False),
    ('transfer_reject', 'OTHER', 'سبب آخر', 'Other', True),
    ('result_amend', 'ENTRY_ERROR', 'خطأ في الإدخال', 'Entry error', False),
    ('result_amend', 'REPEATED_TEST', 'إعادة الفحص', 'Test repeated', False),
    ('result_amend', 'OTHER', 'سبب آخر', 'Other', True),
    ('sample_reject', 'HEMOLYZED', 'عينة متحللة', 'Hemolyzed', False),
    ('sample_reject', 'CLOTTED', 'عينة متجلطة', 'Clotted', False),
    ('sample_reject', 'INSUFFICIENT', 'كمية غير كافية', 'Insufficient volume', False),
    ('sample_reject', 'MISLABELED', 'خطأ في الملصق', 'Mislabeled', False),
    ('sample_reject', 'OTHER', 'سبب آخر', 'Other', True),
]


def seed(apps, schema_editor):
    ReasonCode = apps.get_model("core", "ReasonCode")
    for order, (category, code, label_ar, label_en, requires_note) in enumerate(REASON_CODES):
        ReasonCode.objects.get_or_create(
            category=category,
            code=code,
            defaults={
                "label_ar": label_ar,
                "label_en": label_en,
                "requires_note": requires_note,
                "sort_order": order,
            },
        )


def unseed(apps, schema_editor):
    # Reason codes are referenced by documents; leave them in place when migrating backwards.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_reason_categories_consultation_service"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
