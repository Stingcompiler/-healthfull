# syntax=docker/dockerfile:1.7
# hospital-sys application image: Django 5.2 + django-ninja served by gunicorn.
#
# Build from the repository root (the build context must contain backend/):
#   docker build -f infra/docker/app.Dockerfile --build-arg APP_VERSION=v0.1.0 -t hospital-sys-app:v0.1.0 .
# The sibling app.Dockerfile.dockerignore keeps the context small (BuildKit picks it up).

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.12.15
ARG DEBIAN_RELEASE=bookworm

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------- build
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS build
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first: this layer is reused until pyproject.toml or uv.lock change.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Static files are collected with DEBUG off so the manifest storage (whitenoise) used at
# runtime finds its manifest. The secret key here only satisfies settings import.
RUN DJANGO_DEBUG=0 \
    DJANGO_SECRET_KEY=collectstatic-build-only-not-a-secret \
    STATIC_ROOT=/app/staticfiles \
    /app/.venv/bin/python manage.py collectstatic --noinput --verbosity 1

# ---------------------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS app

ARG APP_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="hospital-sys app" \
      org.opencontainers.image.description="Medical center management system: Django API" \
      org.opencontainers.image.version="${APP_VERSION}"

# WeasyPrint (PDF invoices, results, claims) needs Pango; fonts cover Arabic and Latin so
# printed documents never depend on the internet.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
      fontconfig fonts-dejavu-core fonts-noto-core \
      tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

RUN groupadd --system --gid 10001 hospital \
 && useradd --system --uid 10001 --gid hospital --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin hospital \
 && install -d -o hospital -g hospital -m 0750 /var/lib/hospital /var/lib/hospital/media

# Code and venv are root-owned and read-only for the service user. The container also runs with
# a read-only root filesystem (compose): only /tmp (tmpfs) and the media volume are writable.
COPY --from=build /app /app
COPY --chmod=0755 infra/docker/app-entrypoint.sh /usr/local/bin/app-entrypoint

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    DJANGO_DEBUG=0 \
    APP_VERSION=${APP_VERSION} \
    STATIC_ROOT=/app/staticfiles \
    MEDIA_ROOT=/var/lib/hospital/media \
    XDG_CACHE_HOME=/tmp/.cache \
    TZ=Africa/Khartoum

WORKDIR /app
USER hospital:hospital
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/api/ops/health', timeout=4); sys.exit(0 if r.status == 200 else 1)"]

ENTRYPOINT ["app-entrypoint"]
CMD ["serve"]
