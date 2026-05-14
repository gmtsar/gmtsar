#!/usr/bin/env bash
# Convenience wrapper for `docker run`. Mounts current working dir as /data
# (so output files land on host), passes through orbits if $ORBITS_DIR is set.
#
# Usage:
#   bash docker/run.sh                          # interactive shell
#   bash docker/run.sh p2p_processing ALOS ...  # one-shot command

set -euo pipefail

IMAGE="${IMAGE:-dunyuliu/gmtsar:latest}"
DATA_DIR="$(pwd)"

ARGS=(--rm -it -v "$DATA_DIR:/data" -w /data)

if [[ -n "${ORBITS_DIR:-}" ]]; then
    ARGS+=(-v "$ORBITS_DIR:/opt/gmtsar/orbits:ro")
fi

# Pass through host UID/GID so files created in /data are owned by the user,
# not root. (For this to take effect the image would need a non-root user;
# leaving as a hook for now.)
# ARGS+=(--user "$(id -u):$(id -g)")

exec docker run "${ARGS[@]}" "$IMAGE" "$@"
