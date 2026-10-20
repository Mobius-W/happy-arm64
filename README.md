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
`curl` to the same CDN does work.

### Adopted: `release-image-legacy.yml` (skopeo → classic archive)

`skopeo copy docker://… docker-archive:…` writes a **classic** docker-save tar
with uncompressed `layer.tar` entries, then the workflow `gzip -1`s the outer
tar, publishes it as a Release asset, and self-tests it on the runner with
`docker load` + `node -v` before uploading.

- Release: `image-legacy-cli-1.2.5`
- Asset: `happy-image-cli-1.2.5.tar.gz` — 1,824,248,556 bytes
- sha256: `105690cf1c41e87bc4e4b88419049379f364a77b3572d36e83b351cf9edb3cc4`

On the board, `fetch-release-image.py` downloads the asset in parallel 64 MB
ranges from the signed `release-assets.githubusercontent.com` URL, verifies the
sha256, runs `docker load -i`, then deletes the archive.

### Why not `docker save` (former `release-image.yml`)

`docker save` from a containerd image store on the runner exported some layers
as gzip while labelling them as uncompressed `tar`. The board's containerd then
hashed the compressed bytes as a diffID:

```
apply layer error … wrong diff id calculated on extraction
```

The image metadata loaded (`Loaded image: …`) but no container could start. The
archive was byte-valid (sha256 matched), so this was a format/label bug, not a
transfer corruption. The legacy skopeo archive avoids it entirely. Keep
`release-image.yml` only as a historical record; do not use its output on the
board.

### Alternate: `fetch-happy-image.py`

Downloads the registry layers directly from GHCR as parallel byte ranges with
curl, verifies sha256, assembles a classic docker-save stream and loads it.
Supports resuming finished chunks. Not used for the current deployment.

No credentials or runtime secrets live in this repo.
