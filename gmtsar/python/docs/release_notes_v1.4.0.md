# Release notes — v1.4.0

## 1. Version and date

- **Version:** v1.4.0 (minor — PLAN Phase 3 continued: snaphu csh removal)
- **Date:** 2026-05-14
- **Previous:** v1.3.0 (archived to `docs/release_notes_v1.3.0.md`)

## 2. Summary of scope

Continues Phase 3 csh removal. Wires up the existing-but-untested
`snaphu.py` to replace **both** `snaphu.csh` and `snaphu_interp.csh`
shell-outs in `p2p_stages.py`. Three improvements:

1. **`utils/snaphu.py` → `utils/snaphu`** — renamed to match the no-`.py`
   convention used by every other util. Made executable. The Python script
   unifies the two csh variants via a 3rd `interp` arg:
   - `snaphu.csh   X Y [R]`  →  `snaphu X Y 0 [R]`
   - `snaphu_interp.csh X Y [R]`  →  `snaphu X Y 1 [R]`

2. **Hardcoded sharedir bug fixed.** Like v1.3.0's `slc2amp`, the 2023
   port had `sharedir = '/usr/local/GMTSAR/share/gmtsar'` hardcoded.
   Replaced with `resolve_sharedir()` from `gmtsar_lib`.

3. **`p2p_stages.py` two call sites updated** (line 521 and 647):
   - `snaphu_interp.csh 0.05 0` (iono path, P2P4) →  `snaphu 0.05 0 1`
   - `snaphu_interp.csh|snaphu.csh THRESH DEFOMAX` (P2P5) →
     `snaphu THRESH DEFOMAX <0_or_1>`

## 3. Files added / removed / renamed / cleaned up

### Renamed

- `utils/snaphu.py` → `utils/snaphu` (and `chmod +x`).

### Modified

- `utils/snaphu` — fixed hardcoded sharedir.
- `utils/p2p_stages.py` — two snaphu call sites use Python.

### Added / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.3.0.md` archived to `docs/release_notes_v1.3.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Smoke test post-swap: **6/6 SUCCESS in 205s** (isolated `$SCRATCH=/tmp/slc2amp_smoke`). | ✅ |
| 2. All dev in `gmtsar/python/` | All changes under `gmtsar/python/utils/`. No upstream files touched. | ✅ |

Latent issues fixed:

- **`snaphu.py` hardcoded `/usr/local/GMTSAR/share/gmtsar`** path (same
  pattern as v1.3.0's `slc2amp` fix).

## 6. Remaining open issues, unknowns, or pending bookings

Carried over (no change):

- NISAR_SIM_ALOS download blocked; `enabled: False`.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped via git.
- `dem2topo_ra master.PRM dem.grd` warn-only exit-1.
- Iono path not exercised by test sweep.
- `tests/phase1_test.py` still a scaffold.

Phase 3 remaining csh shell-outs in `p2p_stages.py`: **7** (down from 13).
- `align_tops.csh` × 6 — biggest target (~255 lines csh, lines 282-317 of
  p2p_stages.py).
- `estimate_ionospheric_phase.csh` × 1 (Phase 5 territory, iono path).

Phase 3 cumulative removed: `slc2amp.csh` (v1.3.0), `snaphu.csh` (v1.4.0),
`snaphu_interp.csh` (v1.4.0). 3 of 5 unique csh files in `p2p_stages.py`.

## 7. Totals or cost changes

Source-line totals:

- `utils/snaphu.py` → `utils/snaphu`: 199 lines (same; rename + sharedir fix).
- `utils/p2p_stages.py`: 2 call-site edits, no net line change.

## 8. Assumptions used

- The existing `snaphu.py` (since v0.X) was already a faithful unification
  of `snaphu.csh` + `snaphu_interp.csh`; merely wiring it in is sufficient
  (no logic changes needed).
- Smoke pass with the new code path validates non-iono snaphu (P2P5 dispatch
  is on the smoke path). Iono path (the line 521 call) is still not exercised
  by any test case.
- The C binaries `snaphu` and `nearest_grid` are on PATH (required by both
  the csh and Python versions; unchanged from prior).
