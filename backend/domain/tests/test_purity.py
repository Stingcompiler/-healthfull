"""The domain package must stay pure: no Django (or any app/framework) imports."""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOTS = {"django", "ninja", "pghistory", "pgtrigger", "apps", "api", "config"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            roots.add(node.args[0].value.split(".")[0])
    return roots


def test_domain_has_python_files() -> None:
    assert len(list(DOMAIN_DIR.rglob("*.py"))) >= 4


def test_domain_never_imports_django_or_app_code() -> None:
    offenders = {
        str(path.relative_to(DOMAIN_DIR)): sorted(_imported_roots(path) & FORBIDDEN_ROOTS)
        for path in DOMAIN_DIR.rglob("*.py")
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, f"domain/ must not import framework code: {offenders}"


def test_no_textual_django_references() -> None:
    # Belt and braces: catches importlib.import_module("django...") and similar tricks.
    for path in DOMAIN_DIR.rglob("*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        assert "import django" not in text, path
        assert "from django" not in text, path
        assert "import_module(" not in text, path


def test_detector_catches_forbidden_imports(tmp_path: Path) -> None:
    sample = tmp_path / "bad.py"
    sample.write_text(
        "import django.db\nfrom django.conf import settings\n__import__('ninja')\nimport os\n",
        encoding="utf-8",
    )
    assert _imported_roots(sample) & FORBIDDEN_ROOTS == {"django", "ninja"}
