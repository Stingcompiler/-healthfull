"""django-ninja names an OpenAPI component after the schema class, so two apps that each define
``AllergyOut`` publish one component and the generated TypeScript type silently takes the
shape of whichever loaded last. The clinic schemas keep names no other app uses."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from pydantic import BaseModel

import apps

CLINIC_MODULES = ("apps.clinical.schemas", "apps.orders.schemas")


def _schema_names(module_name: str) -> set[str]:
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        return set()
    return {
        name
        for name, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == module_name
    }


def test_clinic_schema_names_are_not_used_by_other_apps() -> None:
    clinic = {name: module for module in CLINIC_MODULES for name in _schema_names(module)}
    clashes: dict[str, list[str]] = {}
    for info in pkgutil.iter_modules(apps.__path__):
        for suffix in ("schemas", "api"):
            module_name = f"apps.{info.name}.{suffix}"
            if module_name in CLINIC_MODULES:
                continue
            for name in _schema_names(module_name) & clinic.keys():
                clashes.setdefault(name, []).append(module_name)
    assert clashes == {}


def test_clinic_modules_do_not_reuse_a_name_between_themselves() -> None:
    clinical = _schema_names("apps.clinical.schemas")
    orders = _schema_names("apps.orders.schemas")
    assert clinical & orders == set()
