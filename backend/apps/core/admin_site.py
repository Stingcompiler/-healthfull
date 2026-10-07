"""The Django admin site, with the same login rules as the API (ARCHITECTURE 4.10).

The admin login is a second way into a session, and the accounts that can use it are the
most privileged ones, so it must not skip any control the API login has:

* credentials go through ``services.authenticate_credentials`` (per-address throttle,
  per-account lockout, ``AuthEvent`` audit), with a clear message when locked;
* users who still have to change their password are refused, at login and for an
  existing session;
* the session idle timeout and the login/logout audit come from the signal receivers
  in ``apps.core.signals``, shared with the API.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.http import HttpRequest

from apps.core.models import User
from domain.errors import DomainError


class AdminLoginForm(AdminAuthenticationForm):
    error_messages = {
        **AdminAuthenticationForm.error_messages,
        "locked": (
            "This account is temporarily locked after repeated failed logins. "
            "Try again in %(minutes)s minute(s)."
        ),
        "rate_limited": (
            "Too many failed logins from this address. Try again in %(minutes)s minute(s)."
        ),
        "password_change_required": (
            "This account must change its password first. Sign in to the application, "
            "change the password there, then return to the administration site."
        ),
    }

    def clean(self) -> dict[str, Any]:
        from apps.core import services

        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if username is not None and password:
            result = services.authenticate_credentials(
                self.request or HttpRequest(), username, password
            )
            if isinstance(result, DomainError):
                raise self._error_for(result)
            self.user_cache = result
            self.confirm_login_allowed(result)
        return self.cleaned_data

    def _error_for(self, error: DomainError) -> forms.ValidationError:
        minutes = max(1, -(-int(error.details.get("retry_after_seconds", 60)) // 60))
        if error.code == "ACCOUNT_LOCKED":
            return forms.ValidationError(
                self.error_messages["locked"], code="locked", params={"minutes": minutes}
            )
        if error.code == "RATE_LIMITED":
            return forms.ValidationError(
                self.error_messages["rate_limited"],
                code="rate_limited",
                params={"minutes": minutes},
            )
        return self.get_invalid_login_error()

    def confirm_login_allowed(self, user: Any) -> None:
        super().confirm_login_allowed(user)  # active and staff
        if getattr(user, "must_change_password", False):
            raise forms.ValidationError(
                self.error_messages["password_change_required"], code="password_change_required"
            )


class HospitalAdminSite(admin.AdminSite):
    site_header = "Hospital System administration"
    site_title = "Hospital System admin"
    login_form = AdminLoginForm

    def has_permission(self, request: HttpRequest) -> bool:
        user = request.user
        return (
            super().has_permission(request)
            and isinstance(user, User)
            and not user.must_change_password
        )
