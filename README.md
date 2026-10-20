# happy-arm64

Cloud-built `linux/arm64` standalone image of [slopus/happy](https://github.com/slopus/happy) for the WF7000A board.

- Upstream tag: `cli-1.2.5` (`4beb3543cfdeb507be838016996f7a0f65cf7b49`)
- Dockerfile: repository root `Dockerfile` — standalone PGlite + local files, no Postgres/Redis/S3
- Image: `ghcr.io/mobius-w/happy-arm64:cli-1.2.5` (also `:latest`)
- Runner: `ubuntu-24.04-arm` native, no QEMU

This repo intentionally contains only the build recipe; the source is checked out from upstream inside the workflow.

The upstream root Dockerfile does **not** include the webapp. The server still answers `GET /` with `Welcome to Happy Server!`, which is what the mobile app validates when adding a custom server. A separate webapp image would need `Dockerfile.webapp`.

## Pulling where GHCR stalls

On the WF7000A network the GHCR registry client connects but never moves bytes;
`curl` to the same CDN does work. Two fallbacks ship here:

1. `release-image.yml` — pull the image on an arm64 runner, `docker save | gzip`,
   publish it as a Release asset. Fetch on the board through the stable
   `api.github.com` asset endpoint with `curl -fL -C -`, then `docker load`.
2. `fetch-happy-image.py` — download the registry layers as parallel byte
   ranges with curl, verify sha256, assemble a docker-save stream and load it.
   Supports resuming finished chunks.

No credentials or runtime secrets live in this repo.
