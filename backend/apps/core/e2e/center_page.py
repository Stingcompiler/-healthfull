"""Sample content of the public center page for the e2e and demo datasets (test values)."""

from __future__ import annotations

import pghistory

from apps.core.models import Announcement, CenterPage, PublicSiteSettings, User
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
        page.save()
    if not Announcement.objects.exists():
        Announcement.objects.create(
            title_ar="المختبر يفتح من الساعة 7 صباحًا",
            title_en="The laboratory opens at 7 am",
            body_ar="تُسحب عينات الصيام من 7 إلى 10 صباحًا.",
            body_en="Fasting samples are taken from 7 to 10 am.",
            created_by=author,
        )


def seed_public_site(author: User) -> None:
    """Every public switch on (a new install starts with them off)."""
    PublicSiteSettings.load()
    with pghistory.context(user=author.pk, reason="public site: sample dataset"):
        PublicSiteSettings.objects.filter(pk=PublicSiteSettings.SINGLETON_PK).update(
            site_enabled=True, online_booking_enabled=True, patient_tracking_enabled=True
        )
