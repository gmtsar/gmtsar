# GMTSAR Python framework

Python implementations of GMTSAR's heavy per-pixel **compute kernels** (cross-
correlation, phase difference, resampling, SAT geometry, biharmonic surface,
blockmedian, phase filter, plus selected grdmath/grdsample operators), wired
default-on at their primary call sites and verified bit-faithful to the csh/C
pipeline across a 21-case satellite matrix (20/21 clean; the one diff is the
documented Ridgecrest no-DEM corner).

**This is a hybrid, not a pure-Python or GMT-free pipeline.** A working **GMT
(≥6.4) install is required** — at runtime (~60 `gmt` subcommands for grid I/O,
projection, and visualization are never ported; most invocations of even the
*ported* operators still call `gmt`) and at build time (gmtsar's C binaries
link `libgmt`). The C/Fortran SAR preprocessors and snaphu (phase unwrapping)
also remain C. See `docs/release_notes/release_notes_v2.4.0.md` → *Scope & dependencies*, and `docs/PATHWAY_FORWARD.md` for the current, up-to-date porting status.

## Installation

One consolidated installer: `gmtsar/python/install.sh`. It builds gmtsar **in-place** from this checkout (no system-wide install, no re-clone). Each step is an independent flag — combine as needed:

| Flag | What it does |
|---|---|
| `--ubuntu` | apt-install system deps (csh, gmt, gfortran, …) — **requires sudo** |
| `--conda`  | use an existing conda env for build deps + Python packages — **no sudo**. Default env name `gmtsar` (override with `CONDA_GMTSAR_ENV=<name>`). Mutually exclusive with `--ubuntu`. |
| `--python` | install Python packages (skimage, xarray, netcdf4, tk, …) into apt or the conda env, depending on mode |
| `--build`  | autoconf + configure + make + make install (lands in `<repo>/bin`); also builds the FFTW shim and symlinks Python utils + csh scripts into `<repo>/bin` |
| `--orbits` | fetch `ORBITS.tar` (~5-7 GB) into `<repo>/orbits` |
| `--all`    | shortcut for `--ubuntu --python --build` (omits the large orbits download) |

Typical first runs:
```
# Ubuntu / sudo path:
bash gmtsar/python/install.sh --all

# Shared-server / no-sudo path:
bash gmtsar/python/install.sh --conda --python --build
```

Then export the env vars printed at the end:
```
export GMTSAR=<this repo>
export PATH=$GMTSAR/bin:$PATH
```

**`--conda` mode:** also put the conda env on PATH so `gmt` (and other
build-env tools) are found — the line above only adds `$GMTSAR/bin`:
```
conda activate gmtsar            # or: export PATH=$CONDA_PREFIX/bin:$PATH
```
(In `--ubuntu` mode `gmt` is installed system-wide and already on PATH, so
this step is not needed.)

Sanity check:
```
p2p_processing       # prints the usage/help message
gmt --version        # confirms gmt is reachable (needed for actual runs)
```

# Testing for developers

The test runner writes everything under a single work directory, resolved in this order:

1. `$SCRATCH/py.test/` — used if the `SCRATCH` environment variable is set
2. `gmtsar/python/work/` — default (inside this Python folder; gitignored)

Layout under the work directory:

```
<workdir>/
├── dataset/<caseName>.tar.gz    # downloaded raw tarballs (topex sample archive)
├── recipes/                     # per-case Python run scripts (README_<caseName>.txt)
├── results/<caseName>.json      # machine-readable comparison results (compare.py)
├── python_test/<caseName>/...   # Python framework run outputs
└── csh_test/<caseName>/...      # legacy csh reference results
```

For each case, `tests/runner.py`:
1. Downloads `<caseName>.tar.gz` from `topex.ucsd.edu/gmtsar/tar/` into `dataset/` (if not cached).
2. Extracts the tarball **into both trees** — `csh_test/<caseName>/` and `python_test/<caseName>/` — so each tree is a fully self-contained dataset.
3. In `csh_test/<caseName>/`: runs the **bundled `README.txt`** (legacy csh recipe shipped in the tarball) with `csh README.txt > log.txt 2>&1`. Skipped if `intf/` already has outputs.
4. In `python_test/<caseName>/`: copies `recipes/README_<caseName>.txt` (your Python recipe) and runs it with `./README_<caseName>.txt > log.txt 2>&1`.
5. After all cases finish, `tests/compare.py` diffs the `.grd`/`.png` outputs and writes both human lines on stdout and per-case JSON to `<workdir>/results/<case>.json`.

Run sweep (full / fast / single case):
```
bash gmtsar/python/tests/sweep.sh             # full sweep, all 21 cases (~3 h cached / ~8 h first run; Ridgecrest-bound)
bash gmtsar/python/tests/sweep.sh --fast      # 12 cases (~27 min, bounded by ENVI_Baja_EQ)
TEST_CASES=RS2_SLC_Hawaii bash gmtsar/python/tests/sweep.sh --fast   # single case (works with --full too)
```

Force a re-run of an already-passing (cached) case: `SWEEP_FORCE=1`.

Inside one sweep: each case runs in its own background bash (`subprocess.Popen` with `start_new_session=True`); within a case, csh and python recipes run in parallel via `tests/case_runner.sh`. Up to `MAX_PARALLEL=4` cases concurrent. `compare.py` is invoked in-process via `runpy` after all cases finish.

## Sample datasets

Test inputs come from the GMTSAR sample archive:
```
http://topex.ucsd.edu/gmtsar/tar/{caseName}.{ext}
```
The full case manifest (satellite, archive extension, tier membership, enabled flag) is defined in `gmtsar/python/tests/cases.py` (`CASES` dict). One case uses `.tgz` instead of `.tar.gz`: `NISAR_SIM_ALOS` (and is `enabled: False` because topex returns HTTP 403 for that archive).

## csh reference results

`tests/compare.py` compares Python-framework outputs against reference results produced by the legacy csh framework. The reference tree lives at `<workdir>/csh_test/<caseName>/...`; intf-subdir paths are auto-discovered from the filesystem (no longer hardcoded). Files compared: `corr_ll.png`, `display_amp_ll.png`, `phasefilt_mask_ll.png`, `corr_ll.grd`, `phasefilt.grd`, `filtcorr.grd`.

If `csh_test/<caseName>/intf/` has no `.grd`/`.png` outputs, `runner.py` automatically runs the bundled `README.txt` (csh recipe) to generate the reference.

A frozen-csh reference can be optionally produced via `tests/freeze_reference.py`, which snapshots current csh outputs into `tests/reference/<caseName>/...`. When present, `compare.py` runs three pairs per file (python-vs-csh, csh-vs-frozen, python-vs-frozen). The reference dir is gitignored (~5.8 GB if produced).

## Notes on the framework
1. Per-case computing time is collected in `<workdir>/timeSpentLog.txt`; stdout from each case is piped to `log.txt` in the case folder. A summary (wall-clock + per-pipeline timings) prints at the end of `runner.py`.
2. `tests/compare.py` does the comparison. Required Python packages are installed by `install.sh --python`. Per-file thresholds live in `PNG_SSIM_THRESHOLD` / `GRD_RMS_THRESHOLD` dicts at the top of the script (phase-named outputs use a complex-domain rms metric that's invariant to 2π wraps).
3. `tests/report.py` aggregates `results/*.json` and emits `<workdir>/sweep_summary.md`.
4. The case manifest, tier membership, and `enabled` flags live in `tests/cases.py` (`CASES` dict).

Version history: see [`docs/release_notes/`](docs/release_notes/) for all release notes (one file per version).

## Acknowledgments

Portions of the 2026-05 testing-system overhaul, consolidated installer (`install.sh`), Docker dev environment (`docker/`), FFTW threading shim (`fftw_force_serial.c`), and vectorized Python xcorr (`xcorr_py`) were developed in collaboration with Anthropic's Claude Code (Claude Opus 4.7).
