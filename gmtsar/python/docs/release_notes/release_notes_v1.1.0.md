# Release notes — v1.1.0

## 1. Version and date

- **Version:** v1.1.0 (minor — new user-facing feature, no API break)
- **Date:** 2026-05-14
- **Previous:** v1.0.0 (archived to `docs/release_notes_v1.0.0.md`)

## 2. Summary of scope

Testing-system refactor and a tiered test mode. All changes confined to `gmtsar/python/tests/` and `gmtsar/python/.gitignore` (rule 2).

## 3. Files added / removed / renamed / cleaned up

### Added

- `tests/case_runner.sh` — externalized per-case shell driver. Replaces the 50-line embedded shell f-string that lived inside `runner.py`'s `case_script()`. Now invokable directly (positional args: `case cshDir pyDir tarball pyReadme timeLog preloadShim`); easier to debug, real syntax highlighting, no `{var}` escaping pitfalls.

### Modified

- `tests/runner.py` — `case_script()` (50-line f-string returning embedded shell) replaced by a 4-line `case_argv()` that builds a positional-argv list for `case_runner.sh`. Net delete ~40 lines from runner; logic offloaded to the external script.
- `tests/cases.py` — added `SMOKE_CASES` and `FAST_CASES` constants and `TEST_TIER` env-var override. New override priority: `TEST_CASES` (explicit list) → `TEST_TIER` (smoke/fast/full) → default full `caseNameList`.
- `tests/sweep.sh` — new `--smoke | --fast | --full | --help` flags that set `TEST_TIER` before invoking `runner.py`. The old usage docs were referencing the deleted `pathListForTest` module; updated to `cases`. Header comment rewritten with the new tier semantics.
- `tests/compare.py` — `compare_files()` now **returns a result dict** in addition to printing the human line. Driver loop collects results per case and writes `<workdir>/results/<case>.json` (machine-readable schema: `{case, generated, comparisons: [{file, type, status, metric_name, metric, threshold, pair, intf, extra}]}`).
- `tests/report.py` — rewritten to load `results/*.json` directly instead of regex-grepping `sweep.log`. Removes ~40 lines of fragile regex parsing; the `parseCmdOutput` text scraping is gone.
- `.gitignore` — added `tests/reference/` (the frozen-csh-output dir, ~5.8 GB if produced; never shipped via git).

### Renamed / removed

None.

## 4. Content updates to master documents

- **`tests/sweep.sh` header** — usage section updated to the new tier flags.
- **`tests/compare.py` module docstring** — describes the new JSON sidecar contract.
- **`tests/report.py` module docstring** — describes the new JSON input path.

(No changes to `README.md`, `CHANGELOG.md`, or `PROJECT_RULES.md` this release.)

## 5. Audit findings and fixes

Audit against `PROJECT_RULES.md`:

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Ran `compare.py` against the existing sweep outputs (no recompute needed; same data as v1.0.0). Result: **84 SUCCESS / 0 FAIL** across 13 cases. NISAR_SIM_ALOS still 403'd at topex (no test executed). | ✅ |
| 2. All dev in `gmtsar/python/` | All 7 modified/added files are under `gmtsar/python/`. No upstream files touched. | ✅ |

Additional checks:
- Smoke-tested the externalized `case_runner.sh` by re-running `TEST_CASES=RS2_SLC_Hawaii python3 runner.py` end-to-end. 6/6 SUCCESS, 3.6s wall (cached). No regression.
- Smoke-tested the tier override by importing `cases` four times with different `TEST_TIER` values; got 1, 4, 14, 14 cases respectively as designed.
- Smoke-tested the JSON pipeline by running `compare.py` → 14 JSONs written → `report.py` read them and emitted the markdown summary. Totals match the previous v1.0.0 baseline (84/0).

No human-judgment fixes were skipped.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.0.0 (still unresolved):

- **NISAR_SIM_ALOS download blocked** — `http://topex.ucsd.edu/gmtsar/tar/NISAR_SIM_ALOS.tgz` returns HTTP 403; other archives at the same path return 200. Server-side permission issue, not a framework defect.
- **Docker image not published.** Dockerfile + build/run scripts exist in `docker/`; never built/pushed (no Docker on the dev server). User-validation pending.
- **No GitHub Actions workflow.** Recommended next step: a workflow that builds the Docker image on tag push and runs `tests/sweep.sh --fast` as a smoke test.

New in v1.1.0:

- **Frozen-csh reference (`tests/reference/`) is gitignored, not shipped.** The three-way comparison code (py vs csh, csh vs frozen, py vs frozen) works end-to-end when the directory is populated locally via `tests/freeze_reference.py`. Eventual distribution path: a GitHub Release asset (~5.8 GB total, dominated by 3.7 GB for S1_Ridgecrest_EQ). Deferred.

## 7. Totals or cost changes

Not applicable to this project.

## 8. Assumptions used

- The bash version in the build/dev environments supports positional-arg parameter expansion (`${1:?msg}`); standard on any Linux/macOS bash 4+.
- xarray reads `.grd` (NetCDF) files via its installed backend (netcdf4 or h5netcdf) — already covered by `install.sh --python`.
- The JSON schema in `results/<case>.json` will remain backward-compatible; consumers should treat unknown keys as additive.
