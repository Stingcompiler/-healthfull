"""Every module app from ARCHITECTURE 4.1 exists as a package, ready for its phase."""

from __future__ import annotations

import importlib

import pytest
from django.apps import AppConfig, apps

STUB_APPS = [
    "patients",
    "visits",
    "catalog",
    "clinical",
    "orders",
    "billing",
    "payments",
    "ledger",
    "pharmacy",
    "lab",
    "claims",
    "reports",
    "portal",
    "imports",
]


@pytest.mark.parametrize("label", [*STUB_APPS, "ops"])
def test_app_config_is_importable_and_named(label: str) -> None:
    module = importlib.import_module(f"apps.{label}.apps")
    configs = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type) and issubclass(obj, AppConfig) and obj is not AppConfig
    ]
    assert len(configs) == 1
    config = configs[0]
    assert config.name == f"apps.{label}"
    assert config.label == label
    assert config.default_auto_field == "django.db.models.BigAutoField"


@pytest.mark.parametrize("label", STUB_APPS)
def test_stub_apps_are_not_installed_yet(label: str) -> None:
    assert not apps.is_installed(f"apps.{label}")


def test_core_and_ops_are_installed() -> None:
    assert apps.get_app_config("core").name == "apps.core"
    assert apps.get_app_config("ops").name == "apps.ops"
