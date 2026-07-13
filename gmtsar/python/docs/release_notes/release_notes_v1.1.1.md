# Release notes — v1.1.1

## 1. Version and date

- **Version:** v1.1.1 (patch — internal refactor, no behavior change)
- **Date:** 2026-05-14
- **Previous:** v1.1.0 (archived to `docs/release_notes_v1.1.0.md`)

## 2. Summary of scope

Removes the hardcoded per-case interferogram-output map (`intfDirList`) in favor of filesystem auto-discovery. The test framework no longer breaks silently when SAR data is re-acquired with new date pairs.

## 3. Files added / removed / renamed / cleaned up

### Modified

- `tests/cases.py` — `intfDirList = {...}` (24 lines of hardcoded `'intf/<datepair>'` entries) deleted; replaced by a comment pointing readers at the new auto-discover function.
- `tests/compare.py` — new `discover_intf_dirs(case)` walks `python_test/<case>/`, `csh_test/<case>/`, and `reference/<case>/` for any subdirectory containing at least one of the `fileNameList` files, returns the sorted union. Driver loop uses the discovered list instead of `intfDirList[case]`.
- `tests/freeze_reference.py` — uses the same discovery against `csh_test/` (no longer imports `intfDirList`).
- `tests/runner.py` — removed unused `intfDirList` import.

### Removed (logical, not file-level)

- `intfDirList` dict in `cases.py`. No file deletion; the dict is gone but the file remains.

## 4. Content updates to master documents

None.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Re-ran `compare.py` against existing sweep outputs. Result: **84 SUCCESS / 0 FAIL** across 13 cases — identical to v1.1.0 baseline. NISAR_SIM_ALOS still 403'd at topex. | ✅ |
| 2. All dev in `gmtsar/python/` | All 4 modified files are under `gmtsar/python/tests/`. No upstream files touched. | ✅ |

**One bug caught during this refactor and fixed before commit:** the first version of `discover_intf_dirs` used `corr_ll.grd` as the sole sentinel. That worked for most cases but missed S1_TOPS subswath dirs (F1/F2/F3) which produce `phasefilt.grd` / `filtcorr.grd` but not `corr_ll.grd`. Test run showed S1A_SLC_TOPS_LA dropped from 10 to 4 comparisons. Fixed by globbing for ANY file in `fileNameList`, then unioning. Re-test: 84/0 restored.

No human-judgment fixes were skipped.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.1.0 (no change):

- NISAR_SIM_ALOS download blocked (topex 403)
- Docker image not yet published / smoke-tested in a real Docker env
- No GitHub Actions workflow
- Frozen-csh reference (~5.8 GB) not shipped via git; would live as a GitHub Release asset

## 7. Totals or cost changes

Not applicable.

## 8. Assumptions used

- `corr_ll.grd`, `phasefilt.grd`, `filtcorr.grd`, and the three `*_ll.png` files are the only output names we'll ever compare. The auto-discover sentinel is the union of `fileNameList`; new comparison targets need to be added to that list.
- The glob `<case_root>/**/<fname>` returns paths in a deterministic order on this filesystem (used for `sorted()` later).
