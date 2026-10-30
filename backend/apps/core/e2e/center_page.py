"""Sample content of the public center page for the e2e and demo datasets (test values)."""

from __future__ import annotations

import pghistory
from django.utils import timezone

from apps.core.models import (
    Announcement,
    CenterFaq,
    CenterPage,
    PublicSiteSettings,
    Testimonial,
    User,
)
from domain.center_page import hours_json, parse_hours

#: Saturday to Thursday 08:00-20:00, Friday closed (weekday 4), as most Sudanese clinics.
HOURS = hours_json(
    parse_hours(
        [{"weekday": d, "closed": d == 4, "opens": "08:00", "closes": "20:00"} for d in range(7)]
    )
)


def seed_center_page(author: User) -> None:
    """Fill the center page once (an edited page is left as it is), add one notice, and switch
    the website, online booking and patient sign-in on (ADR 0028, 0029): the e2e and demo
    datasets show every public page."""
    seed_public_site(author)
    page = CenterPage.load()
    if not page.hours:
        page.about_ar = "مركز للرعاية الأولية والتخصصية، بمختبر وصيدلية داخل المركز."
        page.about_en = "Primary and specialist care, with a laboratory and pharmacy on site."
        page.hours = HOURS
        page.whatsapp = "249912000111"
        page.email = "info@center.example.test"
        page.directions_ar = "شرق الموقف الرئيسي، المبنى الأبيض بجوار الصيدلية."
        page.directions_en = "East of the main bus stop, the white building next to the pharmacy."
        page.hero_title_ar = "رعاية قريبة منك، كل أيام الأسبوع"
        page.hero_title_en = "Care close to home, every day of the week"
        page.hero_text_ar = "عيادات وطب أسرة ومختبر وصيدلية في مبنى واحد."
        page.hero_text_en = "Clinics, family medicine, a laboratory and a pharmacy in one building."
        page.facilities = [
            {"name_ar": "مختبر", "name_en": "Laboratory"},
            {"name_ar": "صيدلية", "name_en": "Pharmacy"},
            {"name_ar": "غرفة انتظار مكيفة", "name_en": "Air-conditioned waiting room"},
        ]
        page.reasons = [
            {
                "title_ar": "نتائج المختبر في نفس اليوم",
                "title_en": "Same-day lab results",
                "text_ar": "معظم التحاليل الروتينية تظهر قبل نهاية الدوام.",
                "text_en": "Most routine tests are ready before closing time.",
            },
        ]
        page.accessibility_ar = "مدخل بلا درج وكرسي متحرك عند الاستقبال."
        page.accessibility_en = "Step-free entrance and a wheelchair at the door."
        page.privacy_ar = "بياناتك محفوظة في خادم المركز ولا تُشارك إلا بإذنك أو بحكم القانون."
        page.privacy_en = (
            "Your data stays on the center's server and is shared only with your consent or by law."
        )
        page.cancellation_policy_ar = "ألغِ موعدك قبل يوم على الأقل ليُعطى لمريض آخر."
        page.cancellation_policy_en = (
            "Cancel at least a day before so the slot can go to another patient."
        )
        page.save()
    if not CenterFaq.objects.exists():
        CenterFaq.objects.create(
            question_ar="هل أحتاج إلى موعد؟",
            question_en="Do I need an appointment?",
            answer_ar="لا، يمكنك الحضور في ساعات العمل. الموعد يقلل الانتظار.",
            answer_en="No, you can come during opening hours. An appointment shortens the wait.",
            created_by=author,
        )
    if not Testimonial.objects.exists():
        Testimonial.objects.create(
            text_ar="تعامل لطيف ونتيجة التحليل في نفس اليوم.",
            text_en="Kind staff and my test result the same day.",
            author_ar="مراجعة من الخرطوم",
            author_en="A patient from Khartoum",
            created_by=author,
            approved_by=author,
            approved_at=timezone.now(),
        )
    if not Announcement.objects.exists():
        Announcement.objects.create(
            title_ar="المختبر يفتح من الساعة 7 صباحًا",
            title_en="The laboratory opens at 7 am",
            body_ar="تُسحب عينات الصيام من 7 إلى 10 صباحًا.",
            body_en="Fasting samples are taken from 7 to 10 am.",
            created_by=author,
        )


def seed_public_site(author: User) -> None:
    """Every public switch on (a new install starts with them off), and booking instant like
    an existing install (approval off, ADR 0029 K1); specs that need approval switch it on.
    Guest booking on, with the per-address daily cap raised (every spec books from 127.0.0.1)
    and a lighter form check (14 bits instead of 18) so a slow CI browser solves it quickly."""
    PublicSiteSettings.load()
    with pghistory.context(user=author.pk, reason="public site: sample dataset"):
        PublicSiteSettings.objects.filter(pk=PublicSiteSettings.SINGLETON_PK).update(
            site_enabled=True,
            online_booking_enabled=True,
            patient_tracking_enabled=True,
            require_approval=False,
            guest_booking_enabled=True,
            max_requests_per_address_day=1000,
            pow_difficulty_bits=14,
        )
