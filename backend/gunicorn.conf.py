"""Gunicorn settings for production (``gunicorn config.wsgi``), driven by env vars."""

from __future__ import annotations

import os

bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{os.environ.get('BACKEND_PORT', '8000')}")
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))
graceful_timeout = 30
# One structured line per request is written by api.middleware.RequestIdMiddleware.
accesslog = None
errorlog = "-"
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
