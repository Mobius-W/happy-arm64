# happy-arm64

Cloud-built `linux/arm64` standalone image of [slopus/happy](https://github.com/slopus/happy) for the WF7000A board.

- Upstream tag: `cli-1.2.5` (`4beb3543cfdeb507be838016996f7a0f65cf7b49`)
- Dockerfile: repository root `Dockerfile` — standalone PGlite + local files, no Postgres/Redis/S3
- Image: `ghcr.io/mobius-w/happy-arm64:cli-1.2.5` (also `:latest`)
- Runner: `ubuntu-24.04-arm` native, no QEMU
- Runtime: `-p 3005:3005`, `/data` volume, `HANDY_MASTER_SECRET` required; `/` answers
  `Welcome to Happy Server!`, `/health` queries PGlite and returns `{"status":"ok",...}`

This repo intentionally contains only the build recipe; the source is checked out from upstream inside the workflow.

The upstream root Dockerfile does **not** include the webapp. The server still answers `GET /` with `Welcome to Happy Server!`, which is what the mobile app validates when adding a custom server. A separate webapp image would need `Dockerfile.webapp`.

## Pulling where GHCR stalls

On the WF7000A network the GHCR registry client connects but never moves bytes;
`curl` to the same CDN does work.

### Adopted: `release-image-direct.yml` (registry blobs → classic archive)

The workflow pulls the image with `skopeo copy docker://… dir:raw`, then builds a
**classic** docker-save archive **by hardlinking the original registry gzip blobs**.
It does not re-compress anything. Before tarring, every layer is checked twice:

1. `sha256(blob) == manifest layer digest` (compressed digest), and
2. `sha256(gzip -dc blob) == config.rootfs.diff_ids[i]` (uncompressed diffID).

Any mismatch fails the run. The archive is `gzip -1`'d and published as a Release asset.

- Release: `image-direct-cli-1.2.5`
- Asset: `happy-image-cli-1.2.5.tar.gz` — **1,672,853,994 bytes**
- sha256: `a27dd31a356234b8553e00b3673eddb525fcbe1fe9afb86172b4ad77f41ba076`

On the board, `fetch-release-image.py` downloads the asset in parallel 64 MiB
ranges from the signed `release-assets.githubusercontent.com` URL, verifies the
sha256, runs `docker load -i`, and keeps the archive for post-load inspection.

### Why the earlier attempts failed (do not reuse)

| Attempt | Output | Failure on board |
|---|---|---|
| `release-image.yml` — `docker save` from a containerd store | 1,824,233,049 B, sha256 `f5e995e4…` | layers re-compressed but labelled uncompressed → `wrong diff id calculated on extraction` |
| `release-image-legacy.yml` — `skopeo docker-archive:` | 1,824,248,556 B, sha256 `105690cf…` | skopeo rewrote the 3.99 GB layer (content store `9792aaa5…` vs output `fbd38a…`) → same diffID error |

Both archives were byte-valid (sha256 matched their Release notes), so this was never transfer corruption.
The root cause is that **classic overlay2 `docker load` does not verify diffIDs**, so the runner self-test
(`docker load` + `node -v`) passed while containerd 2.3.3 on the board rejected the image. `diagnose-layer.yml`
proved the GHCR blob itself hashes to the expected diffID, which is why the direct route preserves the original
blobs untouched. Keep the two old workflows only as historical records.

### Alternate: `fetch-happy-image.py`

Downloads the registry layers directly from GHCR as parallel byte ranges with
curl, verifies sha256, assembles a classic docker-save stream and loads it.
Supports resuming finished chunks. Not used for the current deployment.

No credentials or runtime secrets live in this repo.
