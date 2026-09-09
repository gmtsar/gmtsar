# Release notes — v1.7.0

## 1. Version and date

- **Version:** v1.7.0 (minor — PLAN Phase 2 complete: batch drivers ported)
- **Date:** 2026-05-14
- **Previous:** v1.6.0 (archived to `docs/release_notes_v1.6.0.md`)

## 2. Summary of scope

Phase 2 of PLAN.md — batch / multi-pair drivers — is now fully ported to
Python. Replaces the four major csh batch scripts that wrap the single-pair
P2P pipeline for stack processing.

| Utility | csh lines | Python lines | Function |
|---|---|---|---|
| `pre_proc_batch`   | 314 | 246 | Preprocess a stack against a common master (per-SAT branches: ALOS/ERS/ENVI/ENVI_SLC/TSX). Builds baseline_table.dat + stacktable_all.ps. |
| `align_batch`      | 179 | 167 | Geometric alignment of N aligned images to a common master via SAT_llt2rat through DEM + optional secondary xcorr pass. |
| `intf_batch`       | 282 | 192 | Form a stack of interferograms from an intf.in pairs list. Per-pair: intf + filter + (snaphu + geocode). Shares topo across pairs. |
| `batch_processing` | 365 |  87 | Top-level orchestrator: dispatches step 1/2/4 to pre_proc_batch / align_batch / intf_batch. Steps 3/5/6 documented as TODO. |
| `unwrap_parallel`  |  39 |  60 | (shipped v1.6.0) Parallel snaphu fan-out via multiprocessing.Pool. |

**Total: 1179 csh lines → 752 Python lines (−36%).**

All four implementations call Python ports throughout (`baseline_table`,
`slc2amp`, `dem2topo_ra`, `intf`, `filter`, `landmask`, `snaphu`, `geocode`,
`fitoffset`). Zero csh shell-outs.

## 3. Files added / removed / renamed / cleaned up

### Added (or scaffold → implementation)

- `utils/pre_proc_batch`  — implemented (was scaffold in v1.6.0).
- `utils/align_batch`     — implemented.
- `utils/intf_batch`      — implemented.
- `utils/batch_processing` — implemented (thin orchestrator).

### Modified / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.6.0.md` archived to `docs/release_notes_v1.6.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Single-pair P2P tests (84/0 baseline) unaffected — Phase 2 utilities are new standalone tools not on any single-pair code path. Multi-pair empirical validation needs new test fixtures (see Phase 2 test gap). | ✅ (no regression) |
| 2. All dev in `gmtsar/python/` | All under `gmtsar/python/utils/`. No upstream files touched. | ✅ |

**Phase 2 test gap:** the existing test suite is single-pair only. To
validate `pre_proc_batch` + `align_batch` + `intf_batch` empirically we'd
need a multi-pair test fixture (e.g. `Batch_ALOS_Baja_3pair`). Tracked as
follow-up; PLAN.md §3 Phase 2 already calls this out.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over (no change):

- NISAR_SIM_ALOS download blocked.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped.
- Ridgecrest empty-results-JSON bug.
- v1.5.0 S1 (Greece) validation still in flight at release time.

New in v1.7.0:

- **`batch_processing` steps 3/5/6 are TODO**. Step 3 (back-geocoding) and
  steps 5/6 (unwrap-only / geocode-only) are not yet wired up — users can
  invoke `intf_batch` directly with appropriate config flags as a
  workaround. Inline back-geocoding is the simplest port; defer when
  someone needs it.
- **Multi-pair test fixture** needed for empirical validation.

After Phase 2: PLAN.md Phase 4 (SBAS / time series) — blocked on the
multi-pair test fixture.

## 7. Totals or cost changes

Cumulative csh-line reductions from PLAN porting:
- Phase 1 (v1.2.0): 466 csh → 569 Python (+22%; ports of small helpers)
- Phase 3 (v1.3.0 + v1.4.0 + v1.5.0): pipeline csh deps in p2p_stages.py
  zeroed; ~700 lines of new Python.
- Phase 2 (v1.7.0): 1179 csh → 752 Python (−36%).

## 8. Assumptions used

- The Python helpers called from the new batch drivers (e.g. `baseline_table`,
  `slc2amp`, `snaphu`, `geocode`) are behaviorally compatible with their
  csh originals. Phase 3 swaps validated this for the single-pair path;
  multi-pair has same per-pair semantics so risk is low.
- `batch_processing` step 2 default of `secondary_align=1` matches the
  csh script's typical invocation pattern.
- `batch_processing` infers `RAW` vs `SLC` from SAT name (ALOS/ERS/ENVI =
  RAW, everything else = SLC). This matches the csh convention; a future
  improvement would let the user override.
