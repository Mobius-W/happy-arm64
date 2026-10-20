#!/usr/bin/env python3
"""Fetch the legacy docker-archive Happy image from a signed Release asset URL.

The asset supports byte ranges. Parallel ranges aggregate much better than a
single stream on this network. Chunks resume, the whole file is sha256-checked,
then docker load reads the gzip-compressed classic docker-save stream directly.
"""
import concurrent.futures as cf
import hashlib
import os
import shutil
import subprocess
import sys
import time

URL_FILE = "/tmp/happy-asset-url"
OUT = "/home/mobius/happy-import"
DEST = os.path.join(OUT, "happy-image-cli-1.2.5.tar.gz")
CHUNK = 64 * 1024 * 1024
WORKERS = 12
SIZE = 1672853994
SHA256 = "a27dd31a356234b8553e00b3673eddb525fcbe1fe9afb86172b4ad77f41ba076"
MIN_FREE_GB = 10


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch_chunk(url, start, end, dest):
    want = end - start + 1
    if os.path.exists(dest) and os.path.getsize(dest) == want:
        return
    if os.path.exists(dest):
        os.unlink(dest)
    last = None
    for attempt in range(1, 6):
        try:
            subprocess.run(
                ["curl", "-4", "-L", "-f", "-sS", "--retry", "5",
                 "--retry-delay", "2", "--max-time", "1800",
                 "-r", f"{start}-{end}", "-o", dest, url],
                check=True)
            if os.path.getsize(dest) == want:
                return
            last = f"size {os.path.getsize(dest)} != {want}"
        except subprocess.CalledProcessError as e:
            last = f"curl rc={e.returncode}"
        time.sleep(3 * attempt)
    raise RuntimeError(f"chunk {start}-{end} failed: {last}")


def main():
    free_gb = shutil.disk_usage("/").free / 1073741824
    if free_gb < MIN_FREE_GB:
        raise SystemExit(f"only {free_gb:.1f} GB free, need {MIN_FREE_GB} GB")
    with open(URL_FILE) as f:
        url = f.read().strip()
    try:
        os.unlink(URL_FILE)
    except OSError:
        pass
    if not url.startswith("https://release-assets.githubusercontent.com/"):
        raise SystemExit("unexpected asset URL host")
    os.makedirs(OUT, exist_ok=True)
    cdir = os.path.join(OUT, "chunks")
    os.makedirs(cdir, exist_ok=True)

    if os.path.exists(DEST) and sha256_file(DEST) == SHA256:
        print("image archive already verified", flush=True)
    else:
        ranges = []
        for start in range(0, SIZE, CHUNK):
            end = min(start + CHUNK - 1, SIZE - 1)
            ranges.append((start, end, os.path.join(cdir, f"{start:012d}")))
        started = time.time()
        done = 0
        with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_chunk, url, s, e, p): (s, e)
                       for s, e, p in ranges}
            for fut in cf.as_completed(futures):
                fut.result()
                s, e = futures[fut]
                done += e - s + 1
                rate = done / max(time.time() - started, 1) / 1048576
                print(f"{done*100.0/SIZE:5.1f}% {done/1048576:7.1f}/{SIZE/1048576:.1f} MB "
                      f"{rate:5.2f} MB/s", flush=True)
        tmp = DEST + ".part"
        with open(tmp, "wb") as w:
            for _, _, p in ranges:
                with open(p, "rb") as r:
                    shutil.copyfileobj(r, w, 4 * 1024 * 1024)
        got = sha256_file(tmp)
        if got != SHA256:
            os.unlink(tmp)
            raise SystemExit(f"sha256 mismatch: got {got}")
        os.replace(tmp, DEST)
        shutil.rmtree(cdir, ignore_errors=True)
        print("sha256 verified", flush=True)

    print("docker load...", flush=True)
    subprocess.run(["docker", "load", "-i", DEST], check=True)
    print("docker load complete", flush=True)
    print("archive kept for post-load verification", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
