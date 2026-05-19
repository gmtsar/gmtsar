#!/usr/bin/env bash
# Build the gmtsar Docker image. Tags both VERSION (if given) and :latest.
# Run from anywhere — script cd's to repo root first.
#
# Usage:
#   bash gmtsar/python/docker/build.sh             # tags only :latest
#   bash gmtsar/python/docker/build.sh v0.1.0      # tags :v0.1.0 and :latest

set -euo pipefail

VERSION="${1:-}"
IMAGE="dunyuliu/gmtsar"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../../.." && pwd)
DOCKERFILE="$SCRIPT_DIR/Dockerfile"

# Stage .dockerignore at the repo root for the build (it lives in docker/
# under our "all dev in python/" rule, but docker build looks for it at the
# context root). Removed on exit.
trap 'rm -f "$REPO_ROOT/.dockerignore"' EXIT
cp "$SCRIPT_DIR/.dockerignore" "$REPO_ROOT/.dockerignore"

cd "$REPO_ROOT"
TAGS=(-t "$IMAGE:latest")
[[ -n "$VERSION" ]] && TAGS+=(-t "$IMAGE:$VERSION")

echo "==> docker build ${TAGS[*]} -f $DOCKERFILE ."
docker build "${TAGS[@]}" -f "$DOCKERFILE" .

echo
echo "Built:"
docker images "$IMAGE" --format "  {{.Repository}}:{{.Tag}}  {{.Size}}"
