#!/bin/sh
# Recreate the Happy relay container with the pinned image and limits.
# Data lives on the host at /var/lib/happy/data (mounted as /data).
# Secrets live in /var/lib/happy/happy.env (not in this file, not in the image).
set -eu
NAME=happy-server
IMAGE=${HAPPY_IMAGE:-ghcr.io/mobius-w/happy-arm64:cli-1.2.5}
ENV_FILE=${HAPPY_ENV_FILE:-/var/lib/happy/happy.env}
DATA_DIR=${HAPPY_DATA_DIR:-/var/lib/happy/data}

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" \
  --restart unless-stopped \
  --init \
  --env-file "$ENV_FILE" \
  -e TZ=Asia/Shanghai \
  -p 0.0.0.0:3005:3005 \
  -v "$DATA_DIR:/data" \
  --memory 1g --memory-swap 1536m --cpus 1.5 --pids-limit 256 \
  --security-opt no-new-privileges:true \
  --log-opt max-size=10m --log-opt max-file=3 \
  --stop-timeout 30 \
  --health-cmd "node -e 'fetch(\"http://127.0.0.1:3005/health\").then(r=>r.json()).then(j=>process.exit(j.status===\"ok\"?0:1)).catch(()=>process.exit(1))'" \
  --health-interval 30s --health-timeout 5s --health-retries 3 --health-start-period 120s \
  "$IMAGE"

echo "started $NAME from $IMAGE"
