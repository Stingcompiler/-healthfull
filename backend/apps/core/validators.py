"""Project password validators (AUTH_PASSWORD_VALIDATORS)."""

from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils.translation import get_language

#: Words anyone at a Sudanese clinic would guess first. Matched case-insensitively as a
#: substring of the password once digits and symbols are stripped.
LOCAL_WORDS: tuple[str, ...] = (
    "hospital",
    "clinic",
    "medical",
    "sudan",
    "khartoum",
    "omdurman",
    "password",
    "welcome",
    "مستشفى",
    "مستشفي",
    "عيادة",
    "السودان",
    "الخرطوم",
    "امدرمان",
    "كلمةالسر",
)

#: Shorter words of the center name (articles, "test") are too common to forbid.
_MIN_CENTER_WORD = 5


def _letters(text: str) -> str:
    return re.sub(r"[\W\d_]+", "", text.casefold())


class LocalWordsPasswordValidator:
    """Rejects passwords built on the center's own name or other obvious local words."""

    def _words(self) -> set[str]:
        words = {_letters(w) for w in LOCAL_WORDS}
        from apps.core.models import CenterProfile

        try:
            with transaction.atomic():  # a savepoint, so a failure cannot poison the caller
                center = CenterProfile.objects.filter(pk=CenterProfile.SINGLETON_PK).first()
        except DatabaseError:  # pragma: no cover - e.g. before migrations; the list still applies
            center = None
        if center is not None:
            for name in (center.name_ar, center.name_en):
                words.update(
                    _letters(w)
                    for w in re.split(r"\W+", name)
                    if len(_letters(w)) >= _MIN_CENTER_WORD
                )
        return {w for w in words if w}

    def validate(self, password: str, user: Any = None) -> None:
        letters = _letters(password)
        if any(word in letters for word in self._words()):
            raise ValidationError(_message(_REJECTED), code="password_local_word")

    def get_help_text(self) -> str:
        return _message(_HELP)


# The project ships no compiled gettext catalogs, so the two languages are inline here.
_REJECTED = {
    "ar": "كلمة المرور سهلة التخمين: تحتوي على اسم المركز أو كلمة محلية شائعة.",
    "en": (
        "This password is too easy to guess: it contains the center's name or a common local word."
    ),
}
_HELP = {
    "ar": "يجب ألا تحتوي كلمة المرور على اسم المركز أو كلمات محلية شائعة.",
    "en": "Your password can't contain the center's name or common local words.",
}


def _message(messages: dict[str, str]) -> str:
    return messages["ar"] if (get_language() or "").startswith("ar") else messages["en"]
