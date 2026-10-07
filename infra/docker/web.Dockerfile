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

# The upstream binary carries the file capability cap_net_bind_service. Compose drops every
# capability and sets no-new-privileges, so the kernel refuses to exec a binary that asks for
# one ("exec /usr/bin/caddy: operation not permitted"). Binding 80/443 is instead allowed by
# the namespaced sysctl net.ipv4.ip_unprivileged_port_start=0 in docker-compose.yml.
RUN apk add --no-cache --virtual .setcap libcap-utils \
 && setcap -r /usr/bin/caddy \
 && if getcap /usr/bin/caddy | grep -q cap_; then echo "file capability still set" >&2; exit 1; fi \
 && apk del .setcap

# Caddy runs as an unprivileged user. Its certificates and state go to directories this user
# owns. Not the base image's /data and /config: those are declared VOLUMEs, and a build step's
# change to a VOLUME path may be discarded. The compose named volumes mount here and inherit
# this ownership when first created.
RUN addgroup -S -g 10002 web \
 && adduser -S -D -H -u 10002 -G web -s /sbin/nologin web \
 && install -d -o web -g web -m 0750 /var/lib/caddy /var/lib/caddy/data /var/lib/caddy/config
ENV XDG_DATA_HOME=/var/lib/caddy/data \
    XDG_CONFIG_HOME=/var/lib/caddy/config

COPY infra/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
# Validating provisions the TLS apps, which can create the local CA in Caddy's storage: use a
# throwaway directory so no CA key is ever baked into the image (each clinic's CA is created
# on its own server, in the caddy_data volume).
RUN XDG_DATA_HOME=/tmp/caddy-validate XDG_CONFIG_HOME=/tmp/caddy-validate \
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
 && rm -rf /tmp/caddy-validate

# Last, so a new version does not invalidate the cached layers above.
ARG APP_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="hospital-sys web" \
      org.opencontainers.image.description="Medical center management system: SPA + reverse proxy" \
      org.opencontainers.image.version="${APP_VERSION}"

USER web:web
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8081/index.html"]
