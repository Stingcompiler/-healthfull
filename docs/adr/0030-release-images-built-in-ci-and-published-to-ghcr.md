# 0030: Release images are built in CI and published to ghcr.io

Date: 2026-10-30. Status: accepted (asked for by the owner on 2026-10-30). Related: 0020 (update
history), 0028 (the OVH host). Amends nothing in the seven invariants; changes how images reach a
server, not what `infra/update.sh` does with them.

## Context
The OVH production host is shared with other projects. Every deploy built `app`, `web` and `db`
on it with `infra/compose.sh build` at `nice 19`: about 40 minutes of CPU and memory taken from
the neighbours, then `update.sh --local-images` (or a `docker save` archive). CI already builds the
same three images on every pull request (the `docker` job) and throws them away.

## Decisions
1. **CI publishes, servers pull.** A `publish` job in `.github/workflows/ci.yml` needs every other
   CI job and runs only for a push to `main` or a `v*` tag (CI now also runs on `v*` tags). It
   builds `app`, `web` and `db` for linux/amd64 with the `docker` job's GitHub Actions layer cache
   (same scopes, read only) and pushes them to `ghcr.io/stingcompiler/healthfull/{app,web,db}`
   with `GITHUB_TOKEN` (`packages: write` on that job only). No new secret.
2. **Tags.** `sha-<7 hex>` for every build of `main` (immutable, what a server deploys), `main` for the
   latest main, the git tag for a release, and `16` on the db image (the default `DB_IMAGE_TAG`).
   No `latest`. OCI labels from `docker/metadata-action` (source = the repository, revision,
   created) plus title, version and licence. Provenance attestations are off so every tag is a
   plain single-platform manifest.
3. **Deploy tags never move.** `update.sh` refuses `main` and `latest`: a rollback restarts the
   previous tag, and a moving tag would by then name a different image.
4. **Version check unchanged.** The app reports `APP_VERSION`, which compose sets from
   `APP_IMAGE_TAG`, which `update.sh` sets to the tag it deploys; the health check
   (`version == TAG`) therefore holds for any tag an image is pulled under. The build argument
   `APP_VERSION` (`sha-<7>` or the git tag) only feeds the label and a run outside compose.
5. **The database image keeps its name.** `DB_IMAGE_REGISTRY` (default: `IMAGE_REGISTRY`) names
   the db/backup image separately. A running server that moves app and web to the registry sets
   it to its old value, so the `db` and `backup` services keep their configuration and compose
   never recreates the database container. `update.sh` checks in step 1 that the db/backup image
   is on the host (the backup and any restore run in it) and pulls it only if missing; it never
   builds it in the middle of an update.
6. **Registry optional.** LAN installs without internet keep `--image-archive` and
   `--local-images`; the server can still build when GitHub is unreachable. CI does not attach
   offline archives to releases (three images, several hundred MB each, release write permission
   for a rare need): `docs/runbooks/registry.md` shows how to make one from the registry.
7. **Access.** The packages are private. A server logs in once as root with a classic token
   scoped `read:packages` only (fine-grained tokens cannot read the container registry); the owner
   creates and rotates it. The repository's own visibility does not change the packages'.

## Consequences
- A deploy on the OVH host is `git pull` and `update.sh --tag sha-<7>`: about two minutes.
- An image exists only after the whole CI run on `main` is green; a failing e2e shard blocks
  publishing until it is fixed or re-run.
- A newer push to `main` cancels the older run (CI concurrency), including its `publish`; the
  newer commit's images are the ones published.
- The first switch of a running server needs aliases of the running images under the registry
  name, so that a rollback to the current tag has something to start (registry.md, step 2).

## Alternatives rejected
- **A separate workflow on `workflow_run`.** Same gate, but a second file, a second checkout of
  the triggering commit and harder-to-read status; a job in CI with `needs:` is enough.
- **Building on the server at a lower priority or in off-hours.** Still 40 minutes of a shared
  host per deploy.
- **Publishing `db` under the same registry setting as app and web.** Changing one `.env` line
  would rename the running database image and make the next `up -d` recreate the db container
  (or build it). The separate setting makes that an explicit, optional step.
