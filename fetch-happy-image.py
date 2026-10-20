#!/usr/bin/env python3
"""Fetch the pinned Happy arm64 image from GHCR and hand it to docker load.

Docker's registry client stalls on this network after the CDN redirect, while
curl works. Download each layer as parallel byte ranges, verify sha256, then
build a docker-save tar whose layers are the original gzipped blobs.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

REG = "ghcr.io"
REPO = "mobius-w/happy-arm64"
REF = "cli-1.2.5"
TAG = f"{REG}/{REPO}:{REF}"
OUT = "/var/lib/happy/import"
CHUNK = 32 * 1024 * 1024
WORKERS = 8
MIN_FREE_GB = 8


def curl(args, timeout=1200):
    cmd = ["curl", "-4", "-f", "-sS", "--retry", "5", "--retry-delay", "2",
           "--max-time", str(timeout)] + args
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout


def token():
    raw = curl([f"https://ghcr.io/token?service=ghcr.io&scope=repository:{REPO}:pull"],
               timeout=60)
    return json.loads(raw)["token"]


def manifest():
    raw = curl(["-H", "Accept: application/vnd.oci.image.index.v1+json",
                f"https://ghcr.io/v2/{REPO}/manifests/{REF}"], timeout=60)
    idx = json.loads(raw)
    digest = None
    for m in idx.get("manifests", []):
        p = m.get("platform") or {}
        if p.get("os") == "linux" and p.get("architecture") == "arm64":
            digest = m["digest"]
            break
    if not digest:
        raise SystemExit("no linux/arm64 manifest in index")
    raw = curl(["-H", "Accept: application/vnd.oci.image.manifest.v1+json",
                f"https://ghcr.io/v2/{REPO}/manifests/{digest}"], timeout=60)
    return json.loads(raw)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch_chunk(digest, start, end, dest):
    want = end - start + 1
    if os.path.exists(dest) and os.path.getsize(dest) == want:
        return
    if os.path.exists(dest):
        os.unlink(dest)
    last = None
    for attempt in range(1, 5):
        try:
            t = token()
            curl(["-L", "-r", f"{start}-{end}", "-H", f"Authorization: Bearer {t}",
                  "-o", dest, f"https://ghcr.io/v2/{REPO}/blobs/{digest}"])
            if os.path.getsize(dest) == want:
                return
            last = f"size {os.path.getsize(dest)} != {want}"
        except subprocess.CalledProcessError as e:
            last = f"curl rc={e.returncode}"
        time.sleep(2 * attempt)
    raise RuntimeError(f"chunk {digest[7:19]} {start}-{end} failed: {last}")


def fetch_blob(digest, size, dest):
    if os.path.exists(dest) and sha256_file(dest) == digest.split(":", 1)[1]:
        print(f"[skip] {digest[7:19]} already verified", flush=True)
        return
    cdir = os.path.join(OUT, "chunks", digest.split(":", 1)[1])
    os.makedirs(cdir, exist_ok=True)
    ranges = []
    for start in range(0, size, CHUNK):
        end = min(start + CHUNK - 1, size - 1)
        ranges.append((start, end, os.path.join(cdir, f"{start:012d}")))
    started = time.time()
    done = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_chunk, digest, s, e, p): (s, e, p)
                   for s, e, p in ranges}
        for fut in cf.as_completed(futures):
            fut.result()
            s, e, _ = futures[fut]
            done += e - s + 1
            pct = done * 100.0 / size
            rate = done / max(time.time() - started, 1) / 1024
            print(f"[{digest[7:19]}] {pct:5.1f}% {done/1048576:7.1f}/{size/1048576:.1f} MB "
                  f"{rate:6.0f} KB/s", flush=True)
    tmp = dest + ".part"
    with open(tmp, "wb") as w:
        for _, _, p in ranges:
            with open(p, "rb") as r:
                shutil.copyfileobj(r, w, 1024 * 1024)
    got = sha256_file(tmp)
    if got != digest.split(":", 1)[1]:
        os.unlink(tmp)
        raise RuntimeError(f"sha256 mismatch for {digest}: {got}")
    os.replace(tmp, dest)
    shutil.rmtree(cdir, ignore_errors=True)
    print(f"[ok] {digest[7:19]} {size/1048576:.1f} MB verified", flush=True)


def main():
    free_gb = shutil.disk_usage("/").free / 1073741824
    if free_gb < MIN_FREE_GB:
        raise SystemExit(f"only {free_gb:.1f} GB free, need {MIN_FREE_GB} GB")
    os.makedirs(os.path.join(OUT, "blobs"), exist_ok=True)
    m = manifest()
    cfg = m["config"]
    layers = m["layers"]
    cfg_hex = cfg["digest"].split(":", 1)[1]
    total = cfg["size"] + sum(x["size"] for x in layers)
    print(f"manifest config={cfg_hex[:12]} layers={len(layers)} total={total/1048576:.1f} MB",
          flush=True)

    cfg_path = os.path.join(OUT, f"{cfg_hex}.json")
    if not (os.path.exists(cfg_path) and sha256_file(cfg_path) == cfg_hex):
        curl(["-L", "-H", f"Authorization: Bearer {token()}", "-o", cfg_path,
              f"https://ghcr.io/v2/{REPO}/blobs/{cfg['digest']}"], timeout=120)
    names = []
    for layer in layers:
        hexd = layer["digest"].split(":", 1)[1]
        path = os.path.join(OUT, "blobs", f"{hexd}.tar.gz")
        fetch_blob(layer["digest"], layer["size"], path)
        names.append(f"blobs/{hexd}.tar.gz")

    save_manifest = [{
        "Config": f"{cfg_hex}.json",
        "RepoTags": [TAG],
        "Layers": names,
    }]
    mpath = os.path.join(OUT, "manifest.json")
    with open(mpath, "w") as f:
        json.dump(save_manifest, f)

    print("assembling docker-save stream and loading...", flush=True)
    tar_cmd = ["tar", "-C", OUT, "-cf", "-", "manifest.json", f"{cfg_hex}.json"] + names
    with subprocess.Popen(tar_cmd, stdout=subprocess.PIPE) as tar:
        load = subprocess.run(["docker", "load"], stdin=tar.stdout)
        tar.stdout.close()
        rc = tar.wait()
    if rc != 0 or load.returncode != 0:
        raise SystemExit(f"load failed tar_rc={rc} docker_rc={load.returncode}")
    print("docker load complete", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
