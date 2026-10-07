from __future__ import annotations

from typing import Literal

from ninja import Field, Schema

LanguageCode = Literal["ar", "en"]
ThemeCode = Literal["light", "dark", "warm"]


class LoginIn(Schema):
    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1, max_length=256)


class MeOut(Schema):
    id: int
    username: str
    full_name_ar: str
    full_name_en: str
    roles: list[str] = Field(..., description="Role codes, sorted")
    permissions: list[str] = Field(
        ..., description="Effective permission codes, sorted. For hiding UI only."
    )
    language: LanguageCode | None = Field(
        ..., description="null = never chosen: the client keeps the device's language"
    )
    theme: ThemeCode | None = Field(
        ..., description="null = never chosen: the client follows prefers-color-scheme"
    )
    must_change_password: bool


class PreferencesPatch(Schema):
    language: LanguageCode | None = None
    theme: ThemeCode | None = None


class ChangePasswordIn(Schema):
    old_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)
