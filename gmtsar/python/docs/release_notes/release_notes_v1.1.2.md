# Release notes — v1.1.2

## 1. Version and date

- **Version:** v1.1.2 (patch — internal refactor, no behavior change)
- **Date:** 2026-05-14
- **Previous:** v1.1.1 (archived to `docs/release_notes_v1.1.1.md`)

## 2. Summary of scope

Unifies the per-case manifest into a single `CASES` dict. Replaces 4 parallel data structures (`caseNameList`, `SMOKE_CASES`, `FAST_CASES`, `TGZ_EXCEPTIONS`) and centralizes the archive URL + extension logic. Adds an `enabled` flag per case.

## 3. Files added / removed / renamed / cleaned up

### Modified

- `tests/cases.py` — defines a single `CASES = {name: {satellite, ext, tiers, enabled}}` dict. `caseNameList` is now *derived* from `CASES` filtered by `TEST_CASES` / `TEST_TIER` / `enabled`. New helpers `archive_url(case)` and `archive_path(case)` replace ext-quirk handling that used to live separately in `runner.py` and `sweep.sh`.
- `tests/runner.py` — deleted `TGZ_EXCEPTIONS = {'NISAR_SIM_ALOS'}` constant and `tarball_path()` function; uses `archive_path(case)` from `cases.py` instead.
- `tests/sweep.sh` — single Python one-shot at startup builds `TARBALL[$c]` and `URL[$c]` maps from `cases.archive_path()` / `cases.archive_url()`. Removes 4 separate `[[ "$c" == "NISAR_SIM_ALOS" ]] && ext=tgz` checks that had drifted out of sync risk.

### Behavior change (documented)

- **NISAR_SIM_ALOS** is now `enabled: False` in `CASES`. It no longer shows up in the default `full` tier (was previously included and contributed a 0/0 row to every sweep report). `TEST_CASES=NISAR_SIM_ALOS` still overrides this if a user wants to attempt it. The new sweep shows **13 cases instead of 14**; SUCCESS / FAIL totals are unchanged.

## 4. Content updates to master documents

None.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Re-ran `compare.py` against existing sweep outputs. Result: **84 SUCCESS / 0 FAIL** across 13 enabled cases — identical totals to v1.1.1 baseline. | ✅ |
| 2. All dev in `gmtsar/python/` | All 3 modified files are under `gmtsar/python/tests/`. No upstream files touched. | ✅ |

Smoke-tested all three tiers (smoke=1, fast=4, full=13) by importing `cases` with different `TEST_TIER` values. Verified URL helpers produce correct extensions for both `.tar.gz` and `.tgz` (NISAR_SIM_ALOS).

No human-judgment fixes were skipped.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.1.1 (no change):

- NISAR_SIM_ALOS download blocked (topex 403). Now expressed cleanly via `enabled: False` in the manifest.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference (~5.8 GB) not shipped via git.

## 7. Totals or cost changes

Not applicable.

## 8. Assumptions used

- The `ARCHIVE_URL_PREFIX = 'http://topex.ucsd.edu/gmtsar/tar/'` is stable; if topex moves, only this constant needs updating.
- Anyone using `from cases import intfDirList` or `TGZ_EXCEPTIONS` would see an `ImportError`. Acceptable: this is a self-contained fork; no external consumers.
