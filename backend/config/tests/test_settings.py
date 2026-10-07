from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import structlog
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_list, env_str
from config.logs import build_logging

BACKEND_DIR = Path(__file__).resolve().parents[2]


# --- env helpers ------------------------------------------------------------------------------


def test_env_str() -> None:
    assert env_str("X", "d", {}) == "d"
    assert env_str("X", "d", {"X": "v"}) == "v"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        (" on ", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
        ("", False),
    ],
)
def test_env_bool(raw: str, expected: bool) -> None:
    assert env_bool("B", not expected, {"B": raw}) is expected


def test_env_bool_default_and_invalid() -> None:
    assert env_bool("B", True, {}) is True
    with pytest.raises(ImproperlyConfigured, match="B must be a boolean"):
        env_bool("B", True, {"B": "maybe"})


def test_env_int() -> None:
    assert env_int("I", 5, {}) == 5
    assert env_int("I", 5, {"I": " "}) == 5
    assert env_int("I", 5, {"I": "42"}) == 42
    with pytest.raises(ImproperlyConfigured, match="integer"):
        env_int("I", 5, {"I": "4x"})


def test_env_list() -> None:
    assert env_list("L", ["a"], {}) == ["a"]
    assert env_list("L", ["a"], {"L": "x, y,,z ,"}) == ["x", "y", "z"]
    assert env_list("L", ["a"], {"L": ""}) == []


def test_env_helpers_read_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOSPITAL_TEST_VAR", "7")
    assert env_str("HOSPITAL_TEST_VAR", "") == "7"
    assert env_int("HOSPITAL_TEST_VAR", 0) == 7
    assert env_list("HOSPITAL_TEST_VAR", []) == ["7"]
    monkeypatch.setenv("HOSPITAL_TEST_VAR", "1")
    assert env_bool("HOSPITAL_TEST_VAR", False) is True


# --- settings -------------------------------------------------------------------------------


def test_test_database_name_is_derived_from_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    digest = hashlib.sha1(str(repo_root).encode()).hexdigest()[:8]  # noqa: S324
    assert digest == settings.REPO_HASH
    test_db: Any = settings.DATABASES["default"]["TEST"]
    expected = os.environ.get("TEST_DB_NAME") or f"test_hospital_{digest}"
    assert test_db["NAME"] == expected


def test_test_database_name_defaults_to_repo_hash_without_override() -> None:
    code = "import json, config.settings as s; print(json.dumps([s.TEST_DB_NAME, s.REPO_HASH]))"
    result = _run_settings({}, code)
    assert result.returncode == 0, result.stderr
    name, repo_hash = json.loads(result.stdout)
    assert name == f"test_hospital_{repo_hash}"


def test_test_database_name_env_override() -> None:
    code = "import json, config.settings as s; print(json.dumps(s.DATABASES['default']['TEST']))"
    result = _run_settings({"TEST_DB_NAME": "test_hospital_agent1"}, code)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["NAME"] == "test_hospital_agent1"


@pytest.mark.parametrize("bad", ["hospital_dev", "e2e_hospital_x", "prod"])
def test_test_database_name_override_must_start_with_test(bad: str) -> None:
    result = _run_settings({"TEST_DB_NAME": bad}, "import config.settings")
    assert result.returncode != 0
    assert "TEST_DB_NAME must start with 'test_'" in result.stderr


def test_core_settings() -> None:
    assert settings.AUTH_USER_MODEL == "core.User"
    assert settings.TIME_ZONE == "Africa/Khartoum"
    assert settings.LANGUAGE_CODE == "ar"
    assert settings.USE_TZ is True
    assert settings.SESSION_COOKIE_AGE == 8 * 60 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.CSRF_COOKIE_HTTPONLY is False
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert "apps.core" in settings.INSTALLED_APPS
    assert "apps.ops" in settings.INSTALLED_APPS
    assert "apps.billing" not in settings.INSTALLED_APPS  # stubs only until Phase 1
    assert settings.PGHISTORY_APPEND_ONLY is True


def _run_settings(env: dict[str, str], code: str) -> subprocess.CompletedProcess[str]:
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("DJANGO_", "DB_", "LOG_", "TEST_DB_"))
    }
    clean.pop("DEBUG", None)
    clean.pop("SECRET_KEY", None)
    clean.update(env)
    return subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        env=clean,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_production_requires_secret_key() -> None:
    result = _run_settings({"DJANGO_DEBUG": "0"}, "import config.settings")
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY must be set" in result.stderr


def test_production_settings_from_env() -> None:
    code = (
        "import json, config.settings as s; print(json.dumps({"
        "'debug': s.DEBUG, 'hosts': s.ALLOWED_HOSTS, 'db': s.DATABASES['default']['NAME'],"
        "'host': s.DATABASES['default']['HOST'], 'port': s.DATABASES['default']['PORT'],"
        "'secure': s.SESSION_COOKIE_SECURE, 'csrf_secure': s.CSRF_COOKIE_SECURE,"
        "'origins': s.CSRF_TRUSTED_ORIGINS, 'docs': s.API_DOCS_ENABLED,"
        "'storage': s.STORAGES['staticfiles']['BACKEND'], 'version': s.APP_VERSION,"
        "'proxy': getattr(s, 'SECURE_PROXY_SSL_HEADER', None), 'xff': s.TRUST_X_FORWARDED_FOR}))"
    )
    result = _run_settings(
        {
            "DJANGO_DEBUG": "0",
            "DJANGO_SECRET_KEY": "x" * 50,
            "DJANGO_ALLOWED_HOSTS": "clinic.local,10.0.0.5",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://clinic.local",
            "DJANGO_SECURE_COOKIES": "1",
            "DJANGO_TRUST_X_FORWARDED_PROTO": "1",
            "DJANGO_TRUST_X_FORWARDED_FOR": "1",
            "DB_NAME": "e2e_hospital_abcdef12",
            "PGHOST": "db",
            "PGPORT": "5433",
            "APP_VERSION": "2026.10.1",
        },
        code,
    )
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])
    assert values == {
        "debug": False,
        "hosts": ["clinic.local", "10.0.0.5"],
        "db": "e2e_hospital_abcdef12",
        "host": "db",
        "port": "5433",
        "secure": True,
        "csrf_secure": True,
        "origins": ["https://clinic.local"],
        "docs": False,
        "storage": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        "version": "2026.10.1",
        "proxy": ["HTTP_X_FORWARDED_PROTO", "https"],
        "xff": True,
    }


def test_dev_defaults() -> None:
    code = (
        "import json, config.settings as s; print(json.dumps({"
        "'debug': s.DEBUG, 'db': s.DATABASES['default']['NAME'],"
        "'host': s.DATABASES['default']['HOST'], 'origins': s.CSRF_TRUSTED_ORIGINS,"
        "'hosts': s.ALLOWED_HOSTS, 'docs': s.API_DOCS_ENABLED}))"
    )
    result = _run_settings({"FRONTEND_PORT": "24001"}, code)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])
    assert values == {
        "debug": True,
        "db": "hospital_dev",
        "host": os.environ.get("PGHOST", ""),
        "origins": ["http://localhost:24001", "http://127.0.0.1:24001"],
        "hosts": ["localhost", "127.0.0.1", "[::1]"],
        "docs": True,
    }


def test_generic_env_names_are_ignored() -> None:
    """Playwright's DEBUG=pw:api (and other tools' generic names) must not reach Django."""
    code = "import json, config.settings as s; print(json.dumps([s.DEBUG, s.SECRET_KEY]))"
    result = _run_settings(
        {"DJANGO_DEBUG": "1", "DEBUG": "pw:api", "SECRET_KEY": "from-some-other-tool"}, code
    )
    assert result.returncode == 0, result.stderr
    debug, secret = json.loads(result.stdout.strip().splitlines()[-1])
    assert debug is True
    assert secret != "from-some-other-tool"


def test_invalid_log_format_is_rejected() -> None:
    result = _run_settings({"LOG_FORMAT": "xml"}, "import config.settings")
    assert result.returncode != 0
    assert "LOG_FORMAT" in result.stderr


# --- logging --------------------------------------------------------------------------------


@pytest.mark.parametrize("as_json", [True, False])
def test_build_logging_renders_context(as_json: bool, capsys: pytest.CaptureFixture[str]) -> None:
    config = build_logging(json=as_json, level="INFO")
    renderer = config["formatters"]["structured"]["processors"][-1]
    expected = structlog.processors.JSONRenderer if as_json else structlog.dev.ConsoleRenderer
    assert isinstance(renderer, expected)

    formatter: Any = config["formatters"]["structured"]["()"](
        processors=config["formatters"]["structured"]["processors"],
        foreign_pre_chain=config["formatters"]["structured"]["foreign_pre_chain"],
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    std_logger = logging.getLogger("hospital.test.logging")
    std_logger.handlers = [handler]
    std_logger.propagate = False
    structlog.contextvars.bind_contextvars(request_id="rid-1")
    try:
        std_logger.warning("stdlib message %s", "x")
    finally:
        structlog.contextvars.clear_contextvars()
        std_logger.handlers = []
    line = capsys.readouterr().err.strip().splitlines()[-1]
    if as_json:
        record = json.loads(line)
        assert record["event"] == "stdlib message x"
        assert record["request_id"] == "rid-1"
        assert record["level"] == "warning"
    else:
        assert "stdlib message x" in line
        assert "rid-1" in line
    # Restore the project's configuration for the rest of the session.
    build_logging(json=True, level="INFO")


def test_static_files_are_world_readable_but_uploads_are_not() -> None:
    code = (
        "import json, config.settings as s; "
        "print(json.dumps([s.STORAGES['staticfiles'].get('OPTIONS'), "
        "s.FILE_UPLOAD_PERMISSIONS, s.FILE_UPLOAD_DIRECTORY_PERMISSIONS]))"
    )
    for debug in ("0", "1"):
        env = {"DJANGO_DEBUG": debug, "DJANGO_SECRET_KEY": "x" * 50}
        result = _run_settings(env, code)
        assert result.returncode == 0, result.stderr
        options, upload_file, upload_dir = json.loads(result.stdout)
        assert options == {"file_permissions_mode": 0o644, "directory_permissions_mode": 0o755}
        assert (upload_file, upload_dir) == (0o640, 0o750)


def test_collectstatic_output_is_readable_by_others(tmp_path: Path) -> None:
    code = (
        "import django; django.setup(); "
        "from django.core.management import call_command; "
        "call_command('collectstatic', interactive=False, verbosity=0)"
    )
    env = {
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DJANGO_DEBUG": "0",
        "DJANGO_SECRET_KEY": "x" * 50,
        "STATIC_ROOT": str(tmp_path / "st"),
    }
    result = _run_settings(env, code)
    assert result.returncode == 0, result.stderr
    root = tmp_path / "st"
    assert root.stat().st_mode & 0o005 == 0o005
    for path in root.rglob("*"):
        need = 0o005 if path.is_dir() else 0o004
        assert path.stat().st_mode & need == need, path
