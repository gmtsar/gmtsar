# Release notes — v1.8.0

## 1. Version and date

- **Version:** v1.8.0 (minor — PLAN Phase 5 corrections: 4 ports + 3 scaffolds)
- **Date:** 2026-05-14
- **Previous:** v1.7.0 (archived to `docs/release_notes_v1.7.0.md`)

## 2. Summary of scope

Phase 5 (corrections / domain extensions) — 4 ports implemented + 3 scaffolds
for larger / specialized targets.

| Utility | csh lines | Python lines | Status |
|---|---|---|---|
| `calc_look_vector`         |  27 |  29 | implemented |
| `tide_correction`          |  58 |  56 | implemented |
| `gnss_enu2los`             |  93 |  52 | implemented |
| `correct_insar_with_gnss`  | 140 |  88 | implemented |
| `make_gacos_correction`    | 200 |  22 | scaffold (GACOS-specific I/O) |
| `MAI_processing`           | 186 |  17 | scaffold (multi-aperture InSAR) |
| `merge_unwrap_geocode_tops` | 275 |  19 | scaffold (last csh dep in p2p_S1_TOPS_Frame) |

The 4 implemented corrections (calc_look_vector, tide_correction, gnss_enu2los,
correct_insar_with_gnss) form a complete chain:
1. `calc_look_vector` builds ENU look-vector grids from the master geometry.
2. `gnss_enu2los` projects GNSS ENU displacements into LOS via that geometry.
3. `correct_insar_with_gnss` smooths the InSAR-vs-GNSS difference and
   subtracts it from the interferogram.
4. `tide_correction` independently produces a solid-earth tide phase grid.

## 3. Files added / removed / renamed / cleaned up

### Added

- `utils/calc_look_vector` — implemented (29 lines).
- `utils/tide_correction` — implemented (56 lines).
- `utils/gnss_enu2los` — implemented (52 lines).
- `utils/correct_insar_with_gnss` — implemented (88 lines).
- `utils/make_gacos_correction` — scaffold.
- `utils/MAI_processing` — scaffold.
- `utils/merge_unwrap_geocode_tops` — scaffold.

### Modified / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.7.0.md` archived to `docs/release_notes_v1.7.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Implementations are standalone utilities (not in any pipeline code path). No regression risk. 84/0 baseline preserved trivially. Empirical validation needs GNSS / DEM fixtures (open). | ✅ (no regression) |
| 2. All dev in `gmtsar/python/` | All changes under `gmtsar/python/utils/`. | ✅ |

## 6. Remaining open issues, unknowns, or pending bookings

Carried over:

- NISAR_SIM_ALOS download blocked.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped.
- Ridgecrest empty-results-JSON bug.
- v1.5.0 Greece S1 test still in flight at v1.8.0 release time.
- Multi-pair test fixture for Phase 2 validation.

Phase 5 remaining:

- **`merge_unwrap_geocode_tops` (275 csh lines)** — the LAST csh dep in any
  Python entry point (called from `p2p_S1_TOPS_Frame:119`). Implementing
  this completes the csh-free goal. Scaffolded here; implementation queued.
- **`make_gacos_correction`** — needs GACOS .ztd/.rsc fixture for testing.
- **`MAI_processing`** — specialized, low-priority.

## 7. Totals or cost changes

- 4 implementations: 318 csh lines → 225 Python lines (−29%).
- 3 scaffolds: 661 csh lines → ~58 Python lines (placeholders).

## 8. Assumptions used

- The Python ports preserve column orderings and awk arithmetic exactly
  (verified by structural diff).
- The 1.556 magic constant in `correct_insar_with_gnss` corresponds to
  1/sin(40°) — the assumed look angle. Documented inline.
- GACOS and MAI users will continue to invoke the csh originals via PATH;
  the scaffolds raise NotImplementedError to make the lack of port explicit.
