"""Django settings, fully driven by environment variables (ARCHITECTURE section 3).

Defaults are safe for local development: DEBUG on, a dev-only secret key, localhost-only
hosts, the Homebrew Postgres socket and database ``hospital_dev``. Production must set at
least ``DJANGO_DEBUG=0``, ``DJANGO_SECRET_KEY`` and ``DJANGO_ALLOWED_HOSTS``; see
``backend/.env.example`` for every variable.
"""

from __future__ import annotations

import hashlib
import warnings
from pathlib import Path

import django_stubs_ext
from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_list, env_str
from config.logs import build_logging

# Allows ``ModelAdmin[Model]``-style generics at runtime (typing only).
django_stubs_ext.monkeypatch()

# --- Paths and worktree identity ------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = Path(__file__).resolve().parents[2]
#: First 8 hex chars of sha1(absolute repo root). Isolates DBs/ports between worktrees.
REPO_HASH = hashlib.sha1(str(REPO_ROOT).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

# --- Core ------------------------------------------------------------------------------

# Only the DJANGO_-prefixed names are read. Generic names such as DEBUG are used by other
# tools (Playwright's DEBUG=pw:api, for one) and must never reconfigure the backend.
DEBUG = env_bool("DJANGO_DEBUG", True)

_DEV_SECRET_KEY = "dev-insecure-secret-key-do-not-use-in-production"  # noqa: S105
SECRET_KEY = env_str("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off")
    SECRET_KEY = _DEV_SECRET_KEY

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])

APP_VERSION = env_str("APP_VERSION", "0.1.0-dev")

INSTALLED_APPS = [
    # django.contrib.admin with the project's admin site (same login rules as the API).
    "apps.core.admin_config.HospitalAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "pgtrigger",
    "pghistory",
    "pghistory.admin",
    "ninja",
    "apps.core",
    "apps.ops",
]

MIDDLEWARE = [
    "api.middleware.RequestIdMiddleware",
    "api.middleware.ApiMethodNotAllowedMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "api.middleware.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database --------------------------------------------------------------------------
# Empty HOST/PORT/USER/PASSWORD let libpq use its defaults (local Unix socket, OS user).

# Parallel checkouts get distinct test DBs from REPO_HASH; parallel agents in ONE checkout
# set TEST_DB_NAME. pytest drops this database, so only "test_*" names are accepted.
TEST_DB_NAME = env_str("TEST_DB_NAME", "") or f"test_hospital_{REPO_HASH}"
if not TEST_DB_NAME.startswith("test_"):
    raise ImproperlyConfigured("TEST_DB_NAME must start with 'test_' (pytest drops it).")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("DB_NAME", "hospital_dev"),
        "USER": env_str("PGUSER", ""),
        "PASSWORD": env_str("PGPASSWORD", ""),
        "HOST": env_str("PGHOST", ""),
        "PORT": env_str("PGPORT", ""),
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 0),
        "CONN_HEALTH_CHECKS": True,
        "TEST": {"NAME": TEST_DB_NAME},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth and sessions ----------------------------------------------------------------

AUTH_USER_MODEL = "core.User"

# Every login path (API, Django admin, authenticate()) shares the lockout, throttle and
# audit in apps.core.services.authenticate_credentials.
AUTHENTICATION_BACKENDS = ["apps.core.auth_backends.LockoutBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        # This User keeps names in full_name_ar/full_name_en (first/last_name stay empty).
        "OPTIONS": {
            "user_attributes": ("username", "full_name_en", "full_name_ar", "email", "phone")
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.core.validators.LocalWordsPasswordValidator"},
]

#: Failed logins allowed per client address per window before logins answer 429.
LOGIN_IP_MAX_FAILURES = env_int("LOGIN_IP_MAX_FAILURES", 30)
LOGIN_IP_WINDOW_SECONDS = env_int("LOGIN_IP_WINDOW_SECONDS", 15 * 60)

# Idle timeout: the cookie age is refreshed on every request, so a session dies after
# SESSION_COOKIE_AGE of inactivity. Login narrows it to Policy.session_idle_minutes.
SESSION_COOKIE_AGE = env_int("SESSION_IDLE_SECONDS", 8 * 60 * 60)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

_SECURE_COOKIES = env_bool("DJANGO_SECURE_COOKIES", False)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", _SECURE_COOKIES)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", _SECURE_COOKIES)

# The SPA reads csrftoken and echoes it in the X-CSRFToken header.
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_HEADER_NAME = "HTTP_X_CSRFTOKEN"
CSRF_USE_SESSIONS = False

_frontend_port = env_str("FRONTEND_PORT", "5173")
_dev_origins = [f"http://localhost:{_frontend_port}", f"http://127.0.0.1:{_frontend_port}"]
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", _dev_origins)
# JSON {code, message, details} for /api/ paths, Django's page elsewhere (admin).
CSRF_FAILURE_VIEW = "api.views.csrf_failure"

# --- HTTP security headers ------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 0)
#: Read the client IP from X-Forwarded-For (only behind our own reverse proxy).
TRUST_X_FORWARDED_FOR = env_bool("DJANGO_TRUST_X_FORWARDED_FOR", False)
if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO", False):
    # Only behind our own reverse proxy (Caddy) which sets this header.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- I18N / time ----------------------------------------------------------------------

LANGUAGE_CODE = "ar"
LANGUAGES = [("ar", "العربية"), ("en", "English")]
USE_I18N = True
TIME_ZONE = "Africa/Khartoum"
USE_TZ = True

# --- Static and media -----------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = Path(env_str("STATIC_ROOT", str(BASE_DIR / "staticfiles")))
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env_str("MEDIA_ROOT", str(BASE_DIR / "media")))
# Uploads (patient documents, logos) are not world-readable. The backup sidecar reads them as
# a member of the app's group (infra/docker/db.Dockerfile), so group read is required.
FILE_UPLOAD_PERMISSIONS = 0o640
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o750
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
# STATIC_ROOT only exists after collectstatic (Docker build); in dev/test that is expected.
warnings.filterwarnings("ignore", message="No directory at", category=UserWarning)
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# --- Audit (django-pghistory) ---------------------------------------------------------

# Event tables are append-only: triggers block UPDATE/DELETE on history rows.
PGHISTORY_APPEND_ONLY = True

# --- API ------------------------------------------------------------------------------

#: Serve Swagger UI at /api/docs (bundled assets, no CDN). Off in production by default.
API_DOCS_ENABLED = env_bool("API_DOCS_ENABLED", DEBUG)

# --- Logging --------------------------------------------------------------------------

LOG_LEVEL = env_str("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = env_str("LOG_FORMAT", "json").lower()
if LOG_FORMAT not in {"json", "console"}:
    raise ImproperlyConfigured("LOG_FORMAT must be 'json' or 'console'")
LOGGING = build_logging(json=LOG_FORMAT == "json", level=LOG_LEVEL)
