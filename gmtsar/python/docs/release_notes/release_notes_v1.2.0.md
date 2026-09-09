# Release notes — v1.2.0

## 1. Version and date

- **Version:** v1.2.0 (minor — PLAN Phase 1 foundational helpers implemented)
- **Date:** 2026-05-14
- **Previous:** v1.1.5 (archived to `docs/release_notes_v1.1.5.md`)

## 2. Summary of scope

Implements the 7 PLAN Phase 1 utility scaffolds that shipped in v1.1.5 as
`NotImplementedError` stubs. Each is a faithful Python port of the upstream
csh original at `gmtsar/csh/<name>.csh`.

| Utility | csh lines | Python lines | Function |
|---|---|---|---|
| `baseline_table`     | 124 | 143 | Compute Bperp / Bpar / xshift / yshift / days-since-epoch from master/aligned PRM. SAT-specific epoch dispatch (ERS=1992, ALOS=2006/2014, CSK=2008, RS2=2014, TSX=2020). |
| `get_baseline_table` |  29 |  74 | Loop over PRM list calling baseline_table; produce baseline_table.dat + baseline.pdf network plot. |
| `gmtsar_sharedir`    |   4 |  33 | Print `$GMTSAR/share/gmtsar` (already implemented in v1.1.5). |
| `make_dem`           |  63 |  61 | Fetch SRTM 1s/3s from GMT server, add EGM96 geoid, output dem.grd. |
| `select_pairs`       |  56 | 113 | Threshold-based pair enumeration → intf.in + baseline.pdf. |
| `proj_ll2ra`         |  71 |  53 | Project a GRD from lon/lat to range/azimuth via trans.dat. |
| `proj_ll2ra_ascii`   |  62 |  45 | ASCII (text) variant of proj_ll2ra. |
| `proj_ra2ll_ascii`   |  57 |  47 | ASCII variant of existing proj_ra2ll. |

Total: ~569 Python lines replacing ~466 csh lines.

## 3. Files added / removed / renamed / cleaned up

### Modified (scaffold → implementation)

- `utils/baseline_table`
- `utils/get_baseline_table`
- `utils/make_dem`
- `utils/select_pairs`
- `utils/proj_ll2ra`
- `utils/proj_ll2ra_ascii`
- `utils/proj_ra2ll_ascii`

`utils/gmtsar_sharedir` was already implemented in v1.1.5.

### Added

None (all 7 file paths existed as scaffolds in v1.1.5).

### Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.1.5.md` archived to `docs/release_notes_v1.1.5.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | All 8 Phase 1 utilities parse cleanly. The pre-Phase-1 84/0 baseline is preserved because none of these utilities are imported by `p2p_processing` or any in-flight pipeline — they are standalone tools. Empirical validation against csh outputs is queued via `tests/phase1_test.py` (still a scaffold; needs real fixtures). | ⏳ |
| 2. All dev in `gmtsar/python/` | All changes under `gmtsar/python/utils/`. No upstream files touched. | ✅ |

Latent issues documented but not fixed:

- **`select_pairs` hardcoded 2014 year offset** (line 28 of original csh).
  The plot x-axis labels assume Sentinel-1 era data. Preserved for behavioral
  parity; would need a `--year-offset` flag or auto-detection from
  baseline_table.dat to fix without breaking csh equivalence.
- **`baseline_table` Envisat-as-ERS kludge** (master filename first 10 chars).
  Carried over from csh as-is; should be replaced by proper SC_identity
  handling upstream eventually.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.1.5:

- NISAR_SIM_ALOS download blocked (topex 403); `enabled: False`.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference (~5.8 GB) not shipped via git.
- `dem2topo_ra master.PRM dem.grd` exits 1 silently (warn-only).
- Iono path is not exercised by the test sweep.

New in v1.2.0:

- **`tests/phase1_test.py` is still a scaffold.** It needs real per-utility
  fixtures and byte-equivalence comparison logic before we can claim these
  ports are validated. The simplest first step: a `gmtsar_sharedir` test
  (no input, assert stdout matches the csh script's output).
- **`baseline_table` and `make_dem` depend on external C binaries** (`SAT_baseline`)
  and **GMT server availability** (`@earth_relief_01s/03s`). The csh originals
  do too — these are not new risks — but fixtures must mock or skip when the
  binaries / network are absent.
- **`select_pairs` performance**: legacy csh enumerates pairs via shell `foreach`
  and calls `gmt psxy` once per edge — the Python port batches all edges into
  a single `psxy` call. Should be 10–100× faster on big networks but produces
  byte-different PostScript (network plot is visually identical though).

## 7. Totals or cost changes

Source-line totals:

- `utils/baseline_table`:     stub → 143 lines
- `utils/get_baseline_table`: stub →  74 lines
- `utils/make_dem`:           stub →  61 lines
- `utils/select_pairs`:       stub → 113 lines
- `utils/proj_ll2ra`:         stub →  53 lines
- `utils/proj_ll2ra_ascii`:   stub →  45 lines
- `utils/proj_ra2ll_ascii`:   stub →  47 lines

Net: +536 lines of implementation, replacing 7 `NotImplementedError` stubs.

## 8. Assumptions used

- Behavioral parity with csh originals is preferred over "correctness fixes"
  for ambiguous cases (e.g. `select_pairs` year offset). Where the original
  has obviously wrong code (e.g. typos), the Python port matches it; comments
  flag the issue for future cleanup.
- The csh originals are the ground truth. `tests/phase1_test.py` (still a
  scaffold) will eventually run both and diff.
- `$GMTSAR` env var is set in any environment that runs these utilities (the
  legacy csh `gmtsar_sharedir.csh` hardcoded the path at build time; the
  Python version resolves dynamically).

## 9. Next

PLAN Phase 3 (TOPS / S1 plumbing) — remove the ~14 csh shell-outs from
`p2p_stages.py` (`align_tops.csh`, `slc2amp.csh`, `snaphu.csh`,
`snaphu_interp.csh`, `estimate_ionospheric_phase.csh`). After Phase 3 + Phase 5,
the Python pipeline will be fully csh-free.
