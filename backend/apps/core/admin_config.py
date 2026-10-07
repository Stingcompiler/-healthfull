"""App config that installs ``django.contrib.admin`` with the project's admin site.

Kept out of ``apps/core/apps.py`` so that module declares exactly one AppConfig.
"""

from __future__ import annotations

from django.contrib.admin.apps import AdminConfig


class HospitalAdminConfig(AdminConfig):
    """``django.contrib.admin`` with ``apps.core.admin_site.HospitalAdminSite``."""

    default_site = "apps.core.admin_site.HospitalAdminSite"
