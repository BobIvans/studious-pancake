#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${PR025_IMAGE_TAG:-studious-pancake:pr025-smoke}"
CONTAINER="pr025-smoke-${RANDOM}-${RANDOM}"

cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$ROOT"
docker build --tag "$IMAGE" .

configured_user="$(docker image inspect --format '{{.Config.User}}' "$IMAGE")"
if [[ "$configured_user" != "10001:10001" ]]; then
  echo "unexpected image user: $configured_user" >&2
  exit 1
fi

docker run --detach --name "$CONTAINER" "$IMAGE" >/dev/null
for _ in $(seq 1 45); do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$CONTAINER")"
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  if [[ "$health" == "unhealthy" ]]; then
    docker logs "$CONTAINER" >&2
    exit 1
  fi
  sleep 1
done

health="$(docker inspect --format '{{.State.Health.Status}}' "$CONTAINER")"
if [[ "$health" != "healthy" ]]; then
  docker logs "$CONTAINER" >&2
  echo "container did not become healthy: $health" >&2
  exit 1
fi

docker exec "$CONTAINER" flashloan-bot status --json >/dev/null
docker exec "$CONTAINER" flashloan-bot capabilities --json >/dev/null
docker exec "$CONTAINER" python - <<'PY'
from importlib.util import find_spec
for package in ("numpy", "pandas", "pyarrow", "sklearn", "pytest"):
    if find_spec(package) is not None:
        raise SystemExit(f"development/analytics package leaked into runtime image: {package}")
PY

echo "PR-025 image smoke passed."
