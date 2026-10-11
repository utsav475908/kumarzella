#!/usr/bin/env bash
# Runs on the server (CircleCI calls it over SSH): pull the images for one commit and restart the stack.
#   IMAGE_TAG=<commit sha> ./deploy/remote-deploy.sh      (GHCR_USER set and a registry token on stdin to log in; optional)
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

token=""
[ -t 0 ] || token=$(cat)
if [ -n "${GHCR_USER:-}" ] && [ -n "$token" ]; then
  echo "$token" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
fi

"${compose[@]}" pull
"${compose[@]}" up -d --no-build --remove-orphans

for i in $(seq 1 40); do
  if "${compose[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/readyz')" 2>/dev/null; then
    echo "EdgeLedger ${IMAGE_TAG:-latest} is up"
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 3
done
echo "API did not become ready" >&2
"${compose[@]}" logs --no-color --tail 100 api migrate >&2
exit 1
