# Docker image for the GMTSAR Python framework

## Build

```
bash gmtsar/python/docker/build.sh              # tags :latest
bash gmtsar/python/docker/build.sh v0.1.0       # tags :v0.1.0 and :latest
```

The script runs from anywhere — it `cd`'s to the repo root and stages
`.dockerignore` there for the build, removing it afterward.

Resulting image: `dunyuliu/gmtsar:latest` (~2–3 GB, single-stage Ubuntu 22.04
build with all apt deps + compiled gmtsar binaries + Python framework).

## Run

```
bash gmtsar/python/docker/run.sh                          # interactive shell
bash gmtsar/python/docker/run.sh p2p_processing ALOS ...  # one-shot command
ORBITS_DIR=/path/to/orbits bash docker/run.sh             # with ORBITS mounted
```

Mounts:
- `$PWD` → `/data` (working dir for inputs/outputs)
- `$ORBITS_DIR` → `/opt/gmtsar/orbits` (read-only, if set)

## Publish

```
docker push dunyuliu/gmtsar:v0.1.0
docker push dunyuliu/gmtsar:latest
```

Or set up GitHub Actions on tag push to build + push automatically.

## Future improvements

- Multi-stage build to drop compilers/headers from runtime image (cuts ~70%)
- Non-root user inside the container (currently runs as root)
- Pre-warmed orbit cache for the common satellites
- `tests/sweep.sh` run inside CI as a smoke test before publish
