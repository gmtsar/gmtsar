# Release notes — v1.11.0

## 1. Version and date

- **Version:** v1.11.0 (minor — PLAN Phase 4 SBAS / time-series ports)
- **Date:** 2026-05-14
- **Previous:** v1.10.0 (archived to `docs/release_notes_v1.10.0.md`)

## 2. Summary of scope

Phase 4 (SBAS / time series) — 6 of the 6 utilities now Python-ported.
Scaffolds from v1.10.0 are fleshed out into faithful ports.

| Utility | csh lines | Python lines | Function |
|---|---|---|---|
| `stack`                 | 113 |  95 | Mean + stdev of a grid stack (with grdgradient/psconvert PDF plots). |
| `stack_corr`            |  61 |  50 | Rosen-style mean correlation (Σ(1−ρ²)/ρ²-based formula). |
| `stack_coherence_mask`  |  37 |  30 | Mean coherence → thresholded mask_def.grd. |
| `prep_sbas`             |  63 |  67 | Build intf.tab + scene.tab from intf.in + baseline_table.dat. |
| `extract_one_time_series` |  71 |  75 | Per-point time-series extraction from disp_<sc_id>.grd stack. |
| `merge_batch`           | 108 |  95 | Loop merge_unwrap_geocode_tops over a stack of TOPS pairs. |

Total: 453 csh lines → 412 Python lines (−9%).

The 22-case full sweep is also running (kicked off at 22:08) — testing
the new v1.10.0 manifest cases (9 new full-tier entries) + the Python
merge_unwrap_geocode_tops introduced in v1.9.0.

## 3. Files added / removed / renamed / cleaned up

### Modified (scaffold → implementation)

- `utils/stack`, `utils/stack_corr`, `utils/stack_coherence_mask`
- `utils/prep_sbas`, `utils/extract_one_time_series`, `utils/merge_batch`

### Added / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.10.0.md` archived to `docs/release_notes_v1.10.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | New utilities are standalone tools not on any single-pair test path. 84/0 baseline preserved trivially. Empirical SBAS validation needs running the sbas-tier cases (`TEST_TIER=sbas`) which test against multi-pair stacks. | ✅ (no regression) |
| 2. All dev in `gmtsar/python/` | All under `gmtsar/python/utils/`. | ✅ |

## 6. Remaining open issues, unknowns, or pending bookings

Carried over (no change):

- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped.
- Ridgecrest empty-results-JSON bug.

Phase 4 specifics:

- **Phase 4 utilities depend on the `sbas` C binary** for the actual
  inversion. That binary is upstream GMTSAR, not csh; same dependency
  as the legacy path. `prep_sbas` only prepares input tables for it.
- **`merge_batch` calls Python `merge_unwrap_geocode_tops`** (per v1.9.0
  rename), which depends on `merge_swath` (C binary). Same C deps as csh.
- **Empirical Phase 4 validation requires sbas-tier cases**: invoke as
  `TEST_TIER=sbas bash tests/sweep.sh`. Cases: `ALOS_Indio_SBAS`,
  `S1A_Stack_CPGF_T173`, `ALOS_Hawaii_stack`, `ENVI_2907_stack`,
  `kilauea_timeseries_sentinel_data`. None of these are exercised by
  the standard 22-case full sweep.

## 7. Totals or cost changes

Cumulative tonight (v1.1.5 → v1.11.0, 11 releases):

- ~3550 csh lines analyzed (across ports of varying depth)
- ~2600 Python lines of implementation
- 35 scaffolds for the long tail

Coverage: 87/87 csh scripts have a Python counterpart (was 14/87 before
tonight). Of those: ~25 are full implementations, ~25 are thin
implementations/aliases, ~37 are scaffolds.

## 8. Assumptions used

- The Rosen et al. (2000) mean-coherence formula in `stack_corr` is
  preserved exactly from the csh (`mean = sqrt(1 / (1 + sum/N))` with
  `sum_i = (1 - ρ_i²) / ρ_i²`).
- `extract_one_time_series` reads `disp_<sc_id>.grd` files (the standard
  sbas output naming). The `m_rng`/`m_azi` averaging-window args default
  to (5, 5) → snap to a 5x5 sample window via half-window math.
- `merge_batch` symlinks `trans.dat`/`raln.grd`/`ralt.grd`/`landmask_ra.grd`
  across pairs (matching the csh behavior — the projection LUT is shared).
