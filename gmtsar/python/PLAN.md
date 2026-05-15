# PLAN — extending Python coverage beyond single-pair P2P

## 1. Goal

The Python framework in `gmtsar/python/` currently covers **single-pair P2P only**
(15 of 87 csh utilities ported by name; the rest still shell out to csh from
within Python, or have no Python entry at all). This plan stages the migration
of the remaining high-value csh utilities into Python, prioritized by user
impact and inverse-risk.

**Non-goal:** translating every csh script. Many are thin wrappers over GMT or
GMTSAR C binaries and add no value reimplemented in Python. Focus is on
**user-visible workflows that unlock new capability** (batch / SBAS / TOPS) and
**csh calls embedded in current Python code** (cleanup of internal coupling).

## 2. Current state (audit, 2026-05-14)

- Python utilities with name-matched csh: 15 (`cleanup`, `dem2topo_ra`, `filter`,
  `fitoffset`, `geocode`, `grd2kml`, `intf`, `landmask`, `p2p_processing`,
  `p2p_S1_TOPS_Frame`, `pop_config`, `pre_proc`, `proj_ra2ll`, `sarp`,
  `slc2amp`). Plus `xcorr_py` (vectorized helper, no csh equivalent).
- csh-only: 72 scripts (see README inventory).
- Python shells out to csh from `p2p_stages.py` 14 times — `align_tops.csh` (6x),
  `slc2amp.csh`, `snaphu.csh`, `snaphu_interp.csh` (3x), `estimate_ionospheric_phase.csh`.
- Test baseline: 13 cases × ~6 file comparisons = 84/0 SUCCESS via `tests/sweep.sh`.

## 3. Phases (ordered: low-risk → high-risk; each independently shippable)

### Phase 1 — Foundational helpers (low risk, small wins)

Thin csh wrappers over GMT or PRM-file parsing. Pure translation, no domain
algorithm changes.

| csh | Python target | Why |
|---|---|---|
| `baseline_table` | `utils/baseline_table` | Foundation for SBAS pair selection. ~80 lines. |
| `get_baseline_table` | reuse via `import` | Same module. |
| `gmtsar_sharedir` | `utils/gmtsar_sharedir` | Single-line shell-out site (`subprocess.run(['gmtsar_sharedir.csh'])`) → use `os.environ['GMTSAR']` directly. |
| `make_dem` | `utils/make_dem` | Wraps SRTM fetch + GMT. Useful standalone. |
| `select_pairs` | `utils/select_pairs` | Threshold-based pair picker; pure CSV/text manipulation. |
| `proj_ll2ra`, `proj_ll2ra_ascii`, `proj_ra2ll_ascii` | extend existing `proj_ra2ll` | Sibling projections; share machinery. |

**Test strategy:** new `tests/phase1_test.py` — run csh and Python versions on
the same input, diff stdout / output text files byte-for-byte (no GMT raster
involved). Add to `sweep.sh` as a tier.

**Exit criteria:** all phase-1 utilities byte-identical to csh on at least one
real dataset each. No regression in existing 84/0 baseline.

### Phase 2 — Batch / multi-pair drivers (medium risk, unlocks workflows)

Orchestration over existing single-pair tools. No new algorithms; just looping
+ scheduling.

| csh | Python target | Why |
|---|---|---|
| `pre_proc_batch` | `utils/pre_proc_batch` | Multi-image preprocess; calls existing `pre_proc` per pair. |
| `align_batch` | `utils/align_batch` | Multi-pair align over common master. |
| `intf_batch` | `utils/intf_batch` | Multi-pair interferogram form. |
| `batch_processing` | `utils/batch_processing` | Top-level driver tying preproc+align+intf+filter. |
| `unwrap_parallel` | `utils/unwrap_parallel` | Parallel snaphu over a pairs list (use `subprocess.Popen` start_new_session=True, same pattern as `sweep.sh`). |

**Test strategy:** new test case `Batch_ALOS_Baja_3pair` that re-uses
`ALOS_Baja_EQ` tarball but processes 3 image pairs end-to-end via batch driver.
Diff vs csh `batch_processing` on the same inputs.

**Exit criteria:** 3-pair batch produces identical `intf/*/phasefilt.grd`
between csh and Python paths within existing thresholds.

### Phase 3 — TOPS / S1 plumbing (medium risk, removes internal csh coupling)

Targets the csh calls Python currently embeds. Same baseline, cleaner internals.

| csh | Python target | Why |
|---|---|---|
| `align_tops` | `utils/align_tops` | Called 6x from `p2p_stages.py`; pure orchestration over `ESARP`, `xcorr`, `resamp` binaries. |
| `intf_tops` | `utils/intf_tops` | TOPS-specific interferogram driver. |
| `merge_unwrap_geocode_tops` | `utils/merge_unwrap_geocode_tops` | Multi-burst merge → unwrap → geocode. |
| `snaphu_interp`, `snaphu` | extend `utils/snaphu.py` | Three call sites in `p2p_stages.py` would become direct imports. |
| `create_frame_tops`, `create_merge_input` | `utils/create_frame_tops`, ... | Glue for multi-burst stitching. |
| `slc2amp` | already in Python; remove csh shell-out | Replace `run('slc2amp.csh ...')` at `p2p_stages.py:505` with direct `from slc2amp import ...`. |

**Test strategy:** the existing `S1_Ridgecrest_EQ` and `S1A_SLC_TOPS_*` cases
already exercise these csh calls via Python. Replace one csh call at a time,
re-run those cases, confirm 24/24 SUCCESS holds.

**Exit criteria:** `grep -c "\.csh" gmtsar/python/utils/*.py` drops to 0 (or to a
documented short list of intentionally-delegated tools). S1 cases continue to
pass.

### Phase 4 — SBAS / time series (high value, larger lift)

New domain — paper-grade multi-cycle InSAR.

| csh | Python target | Why |
|---|---|---|
| `prep_sbas` | `utils/prep_sbas` | Generates SBAS input lists. Mostly file I/O. |
| `stack` | `utils/stack` | Stacks multiple unwrapped interferograms. |
| `stack_corr`, `stack_coherence_mask` | `utils/stack_corr`, ... | Coherence-weighted stacking. |
| `extract_one_time_series` | `utils/extract_one_time_series` | Point time-series extraction; numpy-native. |

**Test strategy:** new test tarball (TBD — see open questions) with ~5 pairs
spanning >1 year. Compare csh-stack output vs Python-stack output.

**Exit criteria:** end-to-end SBAS displacement map matches csh output within
the existing GRD RMS threshold.

### Phase 5 — Corrections (lowest priority; optional)

Specialized atmosphere / ionosphere / tide / GNSS corrections. Useful but each
is a self-contained module that doesn't block earlier phases.

- `make_gacos_correction` (+ parallel variant) — GACOS troposphere correction.
- `estimate_ionospheric_phase` — currently called by `p2p_stages.py` for ALOS
  iono path; would let us remove the last embedded csh call there.
- `tide_correction`, `correct_insar_with_gnss`, `gnss_enu2los`,
  `calc_look_vector`, `MAI_processing` — domain-specific add-ons.

**Test strategy:** per-correction unit tests against a known-input/known-output
fixture. No need to add to the main sweep unless a case relies on it.

## 4. Order of operations

Recommended order: 1 → 3 → 2 → 4 → 5.

Rationale:
- Phase 1 deliverables (e.g. `baseline_table`) are inputs to phase 4.
- Phase 3 cleans up internal coupling **before** phase 2 grows new orchestration
  that would also embed csh calls. Doing 2 before 3 means we'd build batch
  drivers around csh shell-outs and have to refactor them twice.

## 5. Per-phase release cadence

Each phase ships as a minor release (`v1.2.0`, `v1.3.0`, ...) with:
- New utility scripts in `gmtsar/python/utils/`.
- Tests added under `gmtsar/python/tests/`.
- Release notes in `gmtsar/python/release_notes_v<x.y.z>.md` (prior moved to `docs/`).
- All 13 existing cases still pass 84/0.

## 6. Risks

- **Phase 3 (TOPS):** `align_tops.csh` is dense (~500 lines, lots of in-place
  PRM/SLC munging). High translation effort, high regression risk on S1 cases.
- **Phase 4 (SBAS):** no reference dataset currently in the test sweep. Need a
  multi-pair time-series tarball before starting — see open question.
- **Phase 2 parallelism:** `unwrap_parallel` competes with the test sweep's own
  `MAX_PARALLEL=4` budget. Document the interaction; avoid nesting.

## 7. Out of scope

- Per-SAT `p2p_*` csh wrappers (`p2p_ALOS2_SCAN_*`, `p2p_ENVI`, `p2p_ERS`,
  `p2p_processing_nsr`): the Python `p2p_processing` driver already covers all
  SATs via dispatch. The csh wrappers are legacy entry points; not worth porting.
- `_linux` variants (`download_sentinel_orbits_linux`, `organize_files_tops_linux`,
  `prep_data_linux`): csh-specific portability shims. Python is OS-portable.
- `gmtsar`, `gmtsar_sharedir` (the executable, not the .csh): GMTSAR core, leave
  to upstream.
- Visualization / KML utilities beyond existing `grd2kml`: dev resources better
  spent on the pipeline.

## 8. Open questions

- **SBAS test fixture:** does `topex.ucsd.edu/gmtsar/tar/` host a multi-pair
  time-series example, or do we curate one? Phase 4 blocks on this.
- **Parallelism budget:** should phase 2 `*_parallel` utilities respect the same
  `MAX_PARALLEL` env var the test sweep uses, or have their own?
- **csh deprecation horizon:** is the long-term goal to remove the csh shell-out
  shims entirely, or keep them as fallback? Affects how aggressively phase 3
  rewrites internals.
