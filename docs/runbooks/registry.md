# Images from the registry — الصور من السجل (ghcr.io)

ADR 0030. The images a server runs are built by GitHub Actions, not on the server. After every
other CI job passes on a push to `main` or on a `v*` tag, the `publish` job of
`.github/workflows/ci.yml` pushes three images (linux/amd64) to the GitHub Container Registry:

| Image | Tags |
|---|---|
| `ghcr.io/stingcompiler/healthfull/app` | `sha-<7 hex>` (every build of `main`), `main` (latest main), `v1.2.3` (release tag) |
| `ghcr.io/stingcompiler/healthfull/web` | same |
| `ghcr.io/stingcompiler/healthfull/db` | same, plus `16` (the `DB_IMAGE_TAG` a new install uses) |

Deploy `sha-<7 hex>` or a release tag. They never move, so a rollback returns to exactly what ran
before. `main` and `latest` move: `infra/update.sh` refuses them.

The packages are private: a server reads them with a token. Logging in is the owner's job. The
registry is optional. A LAN install without internet keeps `--image-archive` (USB) or
`--local-images` (built on the host); see [update-rollback.md](update-rollback.md).

## Which tag to deploy — أي وسم

The tag of a commit is `sha-` plus its first 7 hex digits. On the server, after `git pull`:

```bash
TAG="sha-$(git rev-parse --short=7 HEAD)"
```

The images exist once the CI run of that commit on `main` is green (the `publish` jobs in the
Actions tab, whose summary lists the tags). Earlier, the pull in step 1 fails and nothing changes.

The app reports `APP_IMAGE_TAG` as its version (compose passes it as `APP_VERSION`), and
`update.sh` sets that to the tag it deploys. So the health check (`version == TAG`) holds for any of
the tags above.

## Read token — رمز القراءة (once per server)

On GitHub (account `Stingcompiler`): Settings > Developer settings > Personal access tokens >
**Tokens (classic)** > Generate new token (classic). Scope **`read:packages` only**, an expiry date
(for example 1 year, with a calendar reminder), name it after the server (`ovh-prod-01 ghcr read`).
Fine-grained tokens cannot read the container registry. If the server is ever compromised, revoke
this token; it can only read images.

Docker on the server runs as root, so log in as root (the token is stored in
`/root/.docker/config.json`):

```bash
read -rs GHCR_TOKEN        # paste the token, Enter (not echoed, not in the shell history)
printf '%s' "$GHCR_TOKEN" | sudo docker login ghcr.io -u stingcompiler --password-stdin
unset GHCR_TOKEN
```

When the token expires, pulls fail ("unauthorized" or "denied") and `update.sh` stops in step 1
with nothing changed: make a new token and log in again.

## One-time switch of a running server — التحويل مرة واحدة

For a server that so far built its images itself (`IMAGE_REGISTRY=hospital-sys`), for example the
OVH production in `/opt/healthfull` on `v30-54b8dc6`. Nothing here stops the app or the database.

1. Log in (above), pull the code, check the images of the commit exist:

   ```bash
   cd /opt/healthfull
   git pull --ff-only
   TAG="sha-$(git rev-parse --short=7 HEAD)"
   sudo docker pull "ghcr.io/stingcompiler/healthfull/app:$TAG"
   ```

2. Give the images that run now their registry name too. A rollback restarts the previous tag
   under the **new** registry name; without these two aliases it would have nothing to start.

   ```bash
   CUR="$(grep '^APP_IMAGE_TAG=' .env | cut -d= -f2)"                  # e.g. v30-54b8dc6
   for i in app web; do sudo docker tag "hospital-sys/$i:$CUR" "ghcr.io/stingcompiler/healthfull/$i:$CUR"; done
   ```

3. Point `.env` at the registry, keeping the database image:

   ```bash
   sudo cp -p .env ".env.before-registry-$(date +%Y%m%d)"
   sudo sed -i 's|^IMAGE_REGISTRY=.*|IMAGE_REGISTRY=ghcr.io/stingcompiler/healthfull|' .env
   grep -q '^DB_IMAGE_REGISTRY=' .env \
     && sudo sed -i 's|^DB_IMAGE_REGISTRY=.*|DB_IMAGE_REGISTRY=hospital-sys|' .env \
     || echo 'DB_IMAGE_REGISTRY=hospital-sys' | sudo tee -a .env >/dev/null
   grep -E '^(IMAGE_REGISTRY|DB_IMAGE_REGISTRY|APP_IMAGE_TAG|DB_IMAGE_TAG)=' .env
   ```

   `DB_IMAGE_REGISTRY=hospital-sys` keeps the `db` and `backup` services on the image they run
   now (`hospital-sys/db:16`), so their configuration does not change and compose never recreates
   the database container. The data lives in the `pgdata` volume either way.

   Do step 4 straight after: until it has run, a plain `infra/compose.sh up -d` would look for
   `ghcr.io/.../app:<current tag>`, which only the alias of step 2 provides.

4. Update, as always:

   ```bash
   sudo infra/update.sh --tag "$TAG" --dry-run --yes
   sudo infra/update.sh --tag "$TAG" --yes --restore-db-on-failure
   ```

5. Verify:

   ```bash
   sudo infra/compose.sh ps                                   # app, web on ghcr.io/...:sha-...; db unchanged
   sudo docker inspect -f '{{.Config.Image}}' "$(sudo infra/compose.sh ps -q db)"   # hospital-sys/db:16
   sudo infra/compose.sh exec -T app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/ops/health').read().decode())"
   ```

   The status page shows the new version and the run in the update history.

To go back to building on the host: restore the `.env` copy (or set `IMAGE_REGISTRY=hospital-sys`
and remove `DB_IMAGE_REGISTRY`), then build and update with `--local-images`.

**Optional, later: the db image from the registry too.** Only in a planned window, because the
database restarts (seconds; the data stays in its volume). It is the same Dockerfile, so it is only
worth doing if a release changes `infra/docker/db.Dockerfile`:

```bash
sudo sed -i 's|^DB_IMAGE_REGISTRY=.*|DB_IMAGE_REGISTRY=|' .env
sudo infra/compose.sh pull db backup
sudo infra/compose.sh up -d db backup
```

## Routine deploy — النشر المعتاد

```bash
cd /opt/healthfull
git pull --ff-only
sudo infra/update.sh --tag "sha-$(git rev-parse --short=7 HEAD)" --yes --restore-db-on-failure
```

About two minutes (pull, checks, backup, swap, health), against about 40 minutes of building at
`nice 19`. For a release, `git checkout v1.2.3` and `--tag v1.2.3`. Old images pile up: now and then
`sudo docker image prune` (keeps the images in use).

If GitHub is unreachable or CI is broken, the server can still build (slow):
`sudo env APP_IMAGE_TAG=<tag> nice -n 19 infra/compose.sh build app web`, then
`sudo infra/update.sh --tag <tag> --local-images --yes`. The build names the images after
`IMAGE_REGISTRY`, so `.env` stays as it is; use a tag CI never makes (for example `local-<7 hex>`).

## New install from the registry — تثبيت جديد

In `.env` set `IMAGE_REGISTRY=ghcr.io/stingcompiler/healthfull`, `APP_IMAGE_TAG=<sha-... or release
tag>`, leave `DB_IMAGE_REGISTRY` empty, log in, then `infra/compose.sh pull` and continue with
[install.md](install.md) section 6.

## Offline archive for a LAN install — أرشيف دون إنترنت

On any machine with internet and the token:

```bash
R=ghcr.io/stingcompiler/healthfull T=v1.2.3
docker pull --platform linux/amd64 $R/app:$T && docker pull --platform linux/amd64 $R/web:$T && docker pull --platform linux/amd64 $R/db:$T
docker tag $R/app:$T hospital-sys/app:$T && docker tag $R/web:$T hospital-sys/web:$T && docker tag $R/db:$T hospital-sys/db:16
docker save hospital-sys/app:$T hospital-sys/web:$T hospital-sys/db:16 | gzip > hospital-sys-$T.tar.gz
```

The `hospital-sys/...` names match a LAN install's default `IMAGE_REGISTRY`; then
`infra/update.sh --tag $T --image-archive hospital-sys-$T.tar.gz` as in
[update-rollback.md](update-rollback.md). CI does not attach archives to releases (ADR 0030).
