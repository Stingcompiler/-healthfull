# syntax=docker/dockerfile:1.7
# hospital-sys web image: the React SPA built with Vite, served by Caddy, which also reverse
# proxies /api, /admin and /static to the app container (infra/Caddyfile).
#
# Build from the repository root:
#   docker build -f infra/docker/web.Dockerfile -t hospital-sys-web:v0.1.0 .

ARG NODE_VERSION=24
ARG CADDY_VERSION=2

# ---------------------------------------------------------------------------- build
FROM node:${NODE_VERSION}-bookworm-slim AS build
WORKDIR /src
ENV CI=true \
    npm_config_store_dir=/pnpm-store

# pnpm version comes from package.json "packageManager", the same one developers use.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN PNPM_VERSION="$(node -p "require('./package.json').packageManager.split('@')[1]")" \
 && npm install -g --no-fund --no-audit "pnpm@${PNPM_VERSION}" \
 && pnpm --version
RUN --mount=type=cache,id=pnpm-store,target=/pnpm-store \
    pnpm install --frozen-lockfile

COPY frontend/ ./
RUN pnpm build

# ---------------------------------------------------------------------------- runtime
FROM caddy:${CADDY_VERSION}-alpine AS web
ARG APP_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="hospital-sys web" \
      org.opencontainers.image.description="Medical center management system: SPA + reverse proxy" \
      org.opencontainers.image.version="${APP_VERSION}"

COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

EXPOSE 80 443
