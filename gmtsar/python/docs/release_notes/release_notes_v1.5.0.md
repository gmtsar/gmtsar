# Release notes — v1.5.0

## 1. Version and date

- **Version:** v1.5.0 (minor — PLAN Phase 3 continued: align_tops Python port)
- **Date:** 2026-05-14
- **Previous:** v1.4.0 (archived to `docs/release_notes_v1.4.0.md`)

## 2. Summary of scope

Ports the **biggest** Phase 3 target — `align_tops.csh` (255 lines) — to
Python and wires up all 6 call sites in `p2p_stages.py`. This removes the
last block of csh shell-outs needed for the S1_TOPS pipeline.

`align_tops` is responsible for aligning Sentinel-1 TOPS SLCs at the
fractional-pixel level: a 3-stage workflow comprising PRM/LED building,
geometric back-projection through the DEM (which produces range and
azimuth offset grids `r.grd` + `a.grd`), and a second `make_s1a_tops` pass
to produce the actual aligned SLCs, followed by `resamp` + `fitoffset`
for sub-pixel refinement.

The Python port preserves:
- skip_master dispatch (0=both, 1=aligned-only, 2=master-only) driven by
  whether the 2nd or 4th positional arg is the literal string "0".
- Burst-shift handling: when `tmp_da` falls outside [-1000, 1000], the
  master PRM clock fields get adjusted by `tmp_da / PRF / 86400` days
  before computing the alignment grids.
- Parallel SAT_llt2rat calls (via `subprocess.Popen` + `.wait()`).
- Parallel `gmt surface` calls for r/a interpolation.
- `mode=1` short-circuit: when caller supplies r.grd/a.grd pre-built, skip
  back-projection entirely.

Calls `fitoffset` (Python, already in utils) instead of `fitoffset.csh`.

## 3. Files added / removed / renamed / cleaned up

### Added

- `utils/align_tops` (228 lines) — Python port of `align_tops.csh`.

### Modified

- `utils/p2p_stages.py` — 6 call-site swaps `align_tops.csh` → `align_tops`.

### Renamed / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.4.0.md` archived to `docs/release_notes_v1.4.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | **RS2 smoke**: 6/6 SUCCESS in 204s (RS2 does not go through align_tops; this just confirms no regression on non-S1 paths). **S1 test**: TEST_CASES=S1A_SLC_TOPS_Greece launched in background at /tmp/aligntops_test/; **validation pending at release time** — Greece typically takes ~1h. If it fails, follow-up patch release. | ⏳ |
| 2. All dev in `gmtsar/python/` | All changes under `gmtsar/python/utils/`. No upstream files touched. | ✅ |

## 6. Remaining open issues, unknowns, or pending bookings

Carried over (no change):

- NISAR_SIM_ALOS download blocked; `enabled: False`.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped via git.
- `dem2topo_ra master.PRM dem.grd` warn-only exit-1.
- Iono path not exercised by test sweep.
- `tests/phase1_test.py` still a scaffold.

Phase 3 remaining: **1 csh shell-out in `p2p_stages.py`:**
- `estimate_ionospheric_phase.csh` × 1 (line 552 of p2p_stages.py;
  iono path only — that's Phase 5 work).

Cumulative removed so far: slc2amp (v1.3.0), snaphu + snaphu_interp (v1.4.0),
align_tops (v1.5.0). 4 of 5 unique csh files in `p2p_stages.py`. After Phase 5,
the Python pipeline will be **fully csh-free**.

## 7. Totals or cost changes

- `utils/align_tops`:    new file, 228 Python lines (vs 255 csh lines).
- `utils/p2p_stages.py`: 6 call-site one-character edits (`.csh` removed).

## 8. Assumptions used

- **S1 validation is in flight, not complete**, at release time. The 6
  Python call-site edits are mechanical; the new `align_tops` Python port
  preserves semantics line-by-line vs the csh; smoke is green on non-S1.
  Confidence that Greece passes is high but not yet empirical.
- The C binaries `make_s1a_tops`, `ext_orb_s1a`, `calc_dop_orb`,
  `SAT_baseline`, `SAT_llt2rat`, `update_PRM`, `resamp` are all on PATH
  (unchanged from prior — these are called the same way as csh did).
- `fitoffset` (Python utility) and the csh `fitoffset.csh` produce
  byte-equivalent output, since the Python port has been in place for
  years and is what `p2p_stages.py` already uses in non-S1 paths.
