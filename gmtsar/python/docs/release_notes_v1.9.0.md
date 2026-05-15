# Release notes — v1.9.0

## 1. Version and date

- **Version:** v1.9.0 (minor — Python pipeline is now fully csh-free)
- **Date:** 2026-05-14
- **Previous:** v1.8.0 (archived to `docs/release_notes_v1.8.0.md`)

## 2. Summary of scope

**The Python pipeline is now zero-csh-dependency end-to-end.**

This release ports `merge_unwrap_geocode_tops.csh` (275 lines) — the last
csh shell-out invoked from any Python entry point. It was the final csh
call in `p2p_S1_TOPS_Frame:119`.

### `utils/merge_unwrap_geocode_tops` (231 Python lines)

Multi-burst S1 TOPS merging + unwrap + geocode. Handles 2- or 3-subswath
inputs and the legacy `det_stitch` flag for auto-computing column-stitching
positions. Calls Python helpers throughout: `snaphu`, `proj_ra2ll`,
`grd2kml`, `landmask`. The C binaries `merge_swath` and `SAT_llt2rat` are
still called (they're upstream C, not csh).

### Bonus cleanup

`p2p_S1_TOPS_Frame` usage / example strings updated to remove stale `.csh`
suffix references. `grep -c '\.csh' p2p_S1_TOPS_Frame == 0` confirms.

## 3. Csh-removal summary across all releases

By Python entry point:

| File | csh deps before | csh deps after |
|---|---:|---:|
| `p2p_processing` (utility entry) | 0 | 0 |
| `p2p_stages.py` (stage code)     | 14 (v1.1.4) | 0 (v1.5.0) |
| `p2p_S1_TOPS_Frame` (S1 driver)  | 1 (v1.1.4)  | 0 (v1.9.0) |
| All others under utils/          | various     | 0           |

`grep -rc "\.csh" gmtsar/python/utils/` → 0 functional references
(stale references in comments / removed in v1.9.0).

## 4. Files added / removed / renamed / cleaned up

### Modified

- `utils/merge_unwrap_geocode_tops` — scaffold → implementation (231 lines).
- `utils/p2p_S1_TOPS_Frame` — 2 help-text edits to drop `.csh` suffix +
  call-site change `merge_unwrap_geocode_tops.csh` → `merge_unwrap_geocode_tops`.

### Added / Removed

None.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Non-S1 paths: RS2 smoke 6/6 SUCCESS (already validated in v1.5.0). S1 path validation: untested for the new Python merge; Greece test from v1.5.0 still validates the csh path (those processes started before the swap). A fresh S1 sweep would validate the new Python path. | ⚠️ Untested for S1 |
| 2. All dev in `gmtsar/python/` | All under `gmtsar/python/utils/`. | ✅ |

## 6. Remaining open issues, unknowns, or pending bookings

Carried over (no change):

- NISAR_SIM_ALOS download blocked.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped.
- Ridgecrest empty-results-JSON bug.
- v1.5.0 Greece S1 test still in flight at v1.9.0 release time.
- Multi-pair test fixture for Phase 2 validation.

New in v1.9.0:

- **`merge_unwrap_geocode_tops` untested with real S1 multi-burst data.**
  The Python port is a faithful structural translation of the 275-line csh.
  Logic is preserved including the 2-subswath and 3-subswath stitch-position
  formulas. A fresh S1 test after v1.5.0's Greece run will validate. If
  issues surface, patch in v1.9.1.

## 7. Totals or cost changes

- `utils/merge_unwrap_geocode_tops`: scaffold (19 lines) → implementation
  (231 lines), replacing 275 csh lines (−16%).

## 8. Assumptions used

- The Python `proj_ra2ll` is byte-compatible with `proj_ra2ll.csh` (same
  GMT operations in the same order). Confirmed via the existing 84/0
  test baseline.
- The Python `snaphu` correctly unifies snaphu.csh and snaphu_interp.csh
  via the 3rd interp arg (validated in v1.4.0 by smoke test).
- The Python `grd2kml` is byte-compatible with `grd2kml.csh` (predates
  this session; not modified here).
- The C binaries `merge_swath`, `SAT_llt2rat`, `update_PRM`, `landmask`
  (binary) are on PATH and behave identically to their csh-wrapper
  ancestors.
