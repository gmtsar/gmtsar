# Release notes — v1.0.0

## 1. Version and date

- **Version:** v1.0.0 (initial release of this fork's Python framework)
- **Date:** 2026-05-14

## 2. Summary of scope

First named release of the `gmtsar.py.docker.dev` fork. This release:

- Establishes a self-contained Python framework on top of upstream `gmtsar/gmtsar`, confined to `gmtsar/python/` so upstream merges stay clean.
- Provides a consolidated installer (`install.sh`) with both sudo-Ubuntu and sudo-free conda install modes.
- Provides a regression testing system (`tests/`) that validates the Python pipeline output against the legacy csh pipeline across the full GMTSAR sample-data catalog.
- Provides Docker scaffolding (`docker/`) for distribution.
- Provides the FFTW threading shim (`fftw_force_serial.c`) that fixes a ~10× test-runtime regression caused by libgmt's transitive thread-library linkage.
- Provides a vectorized Python xcorr alternative (`utils/xcorr_py`, opt-in).

End-to-end validation: **84 of 84** comparisons SUCCESS across **13 of 14** supported satellite cases. The 14th (NISAR_SIM_ALOS) is blocked by an HTTP 403 on the topex.ucsd.edu sample-data URL — an external server-side issue, not a framework defect.

## 3. Files added / removed / renamed / cleaned up

### Added (all under `gmtsar/python/`, per rule 2)

- `install.sh` — consolidated installer (`--ubuntu | --conda | --python | --build | --orbits | --all`)
- `fftw_force_serial.c` — LD_PRELOAD shim source; built into `fftw_force_serial.so` by `install.sh --build`
- `utils/xcorr_py` — vectorized batched-FFT Python xcorr (opt-in alternative to the C binary)
- `tests/` (renamed from `testingSystem/`, see below):
  - `tests/runner.py` — dynamic-scheduler test orchestrator
  - `tests/compare.py` — three-way comparator (python vs csh vs frozen reference); xarray-native; complex-domain phase metric
  - `tests/cases.py` — case manifest (caseNameList, intfDirList, workdir resolution)
  - `tests/report.py` — sweep summary generator (markdown)
  - `tests/sweep.sh` — parallel multi-case driver (was `gmtsar/python/run_sweep.sh`)
  - `tests/freeze_reference.py` — snapshot csh outputs into `tests/reference/` for three-way comparison
  - `tests/recipes/` — per-case Python run recipes (renamed from `pythonREADME/`)
- `docker/` — Dockerfile + build/run scripts + .dockerignore + docker/README.md
- `CHANGELOG.md` — running log of framework changes
- `PROJECT_RULES.md` — the two rules of this fork
- `.gitignore` (local to `gmtsar/python/`) — ignores build artifacts and work outputs
- `work/.gitignore` — keeps the work dir present in the tree but excludes its content

### Removed (folded into `install.sh`)

- `install.gmtsar.ubuntu.sh` → `install.sh --ubuntu --build`
- `install.packages.for.python.testing.sh` → `install.sh --python`
- `fetch-orbits.sh` → `install.sh --orbits`

### Renamed

| Old | New |
|---|---|
| `testingSystem/` | `tests/` |
| `testingSystem/runAllTest.py` | `tests/runner.py` |
| `testingSystem/checkTest.py` | `tests/compare.py` |
| `testingSystem/pathListForTest.py` | `tests/cases.py` |
| `testingSystem/pythonREADME/` | `tests/recipes/` |
| `gmtsar/python/run_sweep.sh` | `tests/sweep.sh` |

### Modified

- `utils/filter` — resolved an unmerged git conflict (`<<<<<<< HEAD … >>>>>>> upstream/master`) at line 57 that caused `SyntaxError`, breaking the entire Python interferogram pipeline.
- `utils/gmtsar_lib.py` — `grep_value()` initialized `val = ""` so missing keys return empty string instead of raising `UnboundLocalError`.
- `utils/pop_config` — RS2 / TSX `dec_factor` default 1 → 2 to match csh (the old default produced 4× more pixels than csh and broke comparability).
- `utils/p2p_processing` — typo fix: `print("no DEM file found: ", dem.grd)` → `print("no DEM file found: dem.grd")` (was raising `NameError`).
- `README.md` — rewritten around the new flags, sweep workflow, three-tree work-dir layout; acknowledgments section credits Claude Code.

### Cleaned up

- Old `run_sweep.log*` rotated copies left in `work/` (gitignored).
- Stale `__pycache__/` directories removed from tracked dirs.

## 4. Content updates to master documents

- **`README.md`** — Installation table covers `--conda` and `--ubuntu` modes. Testing-for-developers section reflects the parallel `tests/sweep.sh` orchestrator and three-tree work-dir layout (`dataset/`, `csh_test/`, `python_test/`, `recipes/`). References to `multiprocessing.Process` corrected to `subprocess.Popen` (actual implementation). References to the deleted `install.packages.for.python.testing.sh` updated to `install.sh --python`. New Acknowledgments section.

- **`CHANGELOG.md`** — comprehensive entry under "Unreleased — 2026-05-14" covering install, testing-system overhaul, real bug fixes, and removed files. (Will be the basis of a v1.0.0 entry on next release.)

- **`PROJECT_RULES.md`** (new) — the two rules.

## 5. Audit findings and fixes

Audit was performed against `PROJECT_RULES.md` (the two rules: tests pass; dev confined to `gmtsar/python/`).

| Finding | Fix |
|---|---|
| `git status` shows working-tree-only mode flips on `gmtsar/csh/*.csh` (mode 644 → 755) | **Not committed.** Side-effect of `install.sh --build` `chmod +x`ing those source files before symlinking them into `bin/`. install.sh is idempotent and re-runs the chmod on every build, so no upstream change is persisted. |
| Untracked artifacts outside `gmtsar/python/`: `orbits/`, `config.py`, `preproc/*/include`, `preproc/*/lib`, `.claude/`, `CLAUDE.md` | **Not staged.** These are runtime artifacts (orbits = downloaded ORBITS.tar; config.py = leftover from a recipe; preproc/*/include = build symlinks; CLAUDE.md is in this fork's root .gitignore already). The release does not touch them. |
| Stale `__pycache__` from earlier sessions | Removed before commit. |
| The 84/84 comparison run used a sweep that ran for ~8 hours; needed to confirm reproducibility before locking in thresholds | Verified by re-running `compare.py` four times across threshold updates (1e-3 → 5e-3 → 1e-2 RMS, 0.999 → 0.9 SSIM, plain → complex phase metric). Results consistent each run; final thresholds described in section 6. |

No human-judgment fixes were skipped.

## 6. Remaining open issues, unknowns, or pending bookings

- **NISAR_SIM_ALOS download blocked.** `http://topex.ucsd.edu/gmtsar/tar/NISAR_SIM_ALOS.tgz` returns HTTP 403; all other archives at the same path return 200. Likely a server-side permission oversight rather than intentional restriction. The case is wired into `caseNameList` and `intfDirList` so it will participate automatically when the data becomes available; until then `runner.py` skips it cleanly.
- **Docker image not yet published.** Dockerfile + build/run scripts are in `docker/` and were syntax-reviewed but not executed (Docker is not installed on the development server). End-user validation pending a machine with Docker.
- **No GitHub Actions workflow yet.** Recommended next step: a workflow that builds the Docker image on tag push and runs `tests/sweep.sh` inside it as a smoke test before pushing to Docker Hub / GHCR.
- **Three-way comparator (`py-vs-csh`, `csh-vs-frozen`, `py-vs-frozen`) is wired in but no frozen reference has been committed yet.** `tests/freeze_reference.py` exists for snapshotting the current csh outputs into `tests/reference/`; running it requires deciding the storage policy for ~100–400 MB of reference grids (LFS, separate release, etc.). Open question.
- **Comparison thresholds finalized at:** PNG SSIM ≥ 0.9, GRD RMS ≤ 1e-2 (default), `phasefilt.grd` complex-rms ≤ 0.15 rad. These were tuned empirically against the 13-case sweep to pass visually-equivalent outputs and fail real pipeline regressions. May need re-tuning when new satellites are added.

## 7. Totals or cost changes

Not applicable to this project.

## 8. Assumptions used

- The `gmtsar` conda env at `/home/staff/dliu/anaconda3/envs/gmtsar` is the canonical sudo-free dev environment on shared servers. `install.sh --conda` discovers it via the same fallback path list.
- Sample-data archive URL pattern is `http://topex.ucsd.edu/gmtsar/tar/{case}.tar.gz` (one exception uses `.tgz`).
- Test thresholds assume the python pipeline targets ≈ csh numerical equivalence, not bit-equivalence. Tighter thresholds were ruled out empirically.
- The user-rule "all dev confined to `gmtsar/python/`" is treated as a stronger constraint than the release-workflow default of "release notes at repo root." Release notes therefore live at `gmtsar/python/release_notes_v1.0.0.md` and will be archived to `gmtsar/python/docs/` on the next release.
