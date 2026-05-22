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

## 7b. TODO — port `p2p_S1_TOPS_Frame.csh` to native Python + wire phase_profile

The S1 TOPS family (S1A_SLC_TOPS_*, S1_Larsen_C, S1_Ridgecrest_EQ) is
currently the only pipeline that still runs through a csh recipe end-to-end
(`p2p_S1_TOPS_Frame.csh` → 3 parallel `p2p_processing.csh` per-subswath
→ `merge_unwrap_geocode_tops.csh`). Consequence:

- The Python `phase_profile.py` hooks aren't called inside `.csh` recipes,
  so the per-binary timing JSON (`phase_profile_py.json`) is **missing**
  for all S1 TOPS cases.
- We can only measure their wall time from the sweep log (`DONE <case>
  (Ns)`), not their per-binary breakdown.
- This means perf-snapshot Table 2 (per-binary timing) has a gap for the
  4-5 biggest cases in the sweep — exactly the ones whose internal
  breakdown would be most informative for next-phase optimization.

**The work:**
1. Port `p2p_S1_TOPS_Frame.csh` → `p2p_S1_TOPS_Frame` (Python). Mirror the
   shell flow: parse args, sort SAFE archives, prep aligned PRMs, drive
   `p2p_processing` per-subswath via `multiprocessing.Pool`, then call
   `merge_unwrap_geocode_tops`.
2. Wrap per-subswath `p2p_processing` calls with `phase()` context manager
   so each subswath's `phase_profile_py.json` lands in `F1/`, `F2/`, `F3/`.
3. Aggregate the 3 subswath profiles into a single Frame-level
   `phase_profile_py.json` at the case root (sum binaries across
   subswaths, sum phases).
4. Verify against `S1A_SLC_TOPS_LA`, `S1_Larsen_C`, `S1_Ridgecrest_EQ`
   — must produce bit-identical merge output to the csh recipe.

**Difficulty:** medium. `p2p_S1_TOPS_Frame.csh` is ~250 lines of shell;
no fundamentally new algorithms (it's an orchestrator). Main risk is
matching the csh recipe's parallel-subswath wait/sync pattern exactly so
we don't get races on the shared topo_ra.grd.

**Cleanup payoff:** removes the largest remaining csh shell-out in the
fork's pipeline. After this, the only csh callers are the `align_tops.csh`
chain (Phase 2 of this plan) and `snaphu*.csh` (Phase 4).

**Effort estimate:** 1-2 weeks (1 Mira-port mission + parity validation
sweep + Frame-level profile aggregation).

## 9a. Status snapshot 2026-05-22 (post-v2.0.0)

After v2.0.0 tag at `94ff0b8`, status of every workstream:

**Python ports in production (PATH-wired):**
- xcorr_py (batched FFT, 1.61× vs csh on RS2)
- SAT_llt2rat_py_v2 (Numba JIT cache=True)
- resamp_py_v2 (Numba JIT cache + MADV_SEQUENTIAL fix)
- proj_ra2ll_fast (numpy bilinear)
- SAT_baseline_py (byte-id on 5 datasets)

**Python ports committed but NOT wired:**
- phasediff_py (Mira #28; NotImplementedError for >1000m baseline)
- conv_py + _gmt_native_bf.py (Mira #28; 1.7-3.4× slower than OMP-C)
- make_los_py (Mira #27; byte-id vs gmt grdmath, 6 tests)
- utils/vector.py (Mira #34; 8 @njit primitives, 29 tests)

**GMT replacements — wired:**
- `gmt grdmath FLIPUD` → numpy + gmt_grd_io.write_gmt_grd (Mira #30, 4.6× per call)
- `gmt gmtconvert -bi5d -bo3d` → numpy memmap slice (Mira #19)
- `gmt grdtrack -nl` (bilinear) → proj_ra2ll_lib (Mira #11)

**GMT replacements — parity-tested but NOT wired:**
- `gmt blockmedian` → numba prange byte-id (Mira #25); kept off — at 1 pt/bin
  density in dem2topo_ra, numba is 4× SLOWER than gmt. Useful at higher density.
- `gmt surface` → FMG + anisotropic (Miras #20/#26/#33); rms 3.4e-4 iso,
  6.7e-4 aniso 1:4; needs pixel-reg + Briggs before safe wire-in
- `gmt grd2xyz -s` → numpy (Mira #19); blocked by %lf ASCII pipe requirement
  for SAT_llt2rat_py parity

**GMT subprocesses NOT YET replaced (next mission targets):**
- `gmt grdmath ADD/MUL/SUB/NEG/ABS` chain (10-15 sites in dem2topo_ra + geocode)
- `gmt grdcut -R...` (rare RR branch, geocode)
- `gmt xyz2grd` (dem2topo_ra)
- `gmt grdsample`, `gmt grdimage`, `gmt psconvert`, `gmt grd2cpt`,
  `gmt makecpt` (visualization, low priority)

**Foundations + perf:**
- `utils/gmt_grd_io.py` — GMT-compatible netCDF writer (Mira #23, 16 tests)
- `utils/vector.py` — @njit single-thread primitives (Mira #34, 29 tests)
- `tools/perf_snapshot.py` — rule-7 snapshot CLI (Mira #24)
- numba 0.65.1 installed in production conda env
- MADV_SEQUENTIAL on resamp_py memmap (Mira #35) — expected stripmap perf flip
- Numba v2 JIT cache: resamp_py_v2 + SAT_llt2rat_py_v2
- S1 TOPS phase_profile aggregation (Mira #21)

**Project rules + harness:**
- Rule 8: merge only when tests pass + env-gated wires need path-exercising smoke
- Rule 9: py side MUST NOT modify the csh oracle
- case_runner.sh sentinel — `.oracle_built` invalidates stale oracles
  (framework SHA + tarball md5)

## 9b. Next mission queue (post-v2.0.0, ordered by ROI)

| # | Mission | Tier | Expected savings |
|---|---|---|---|
| 36 | Wire gmt grdmath chain (ADD/MUL/SUB/NEG/ABS) via gmt_grd_io into dem2topo_ra + geocode | 1 | 5-10 s/case |
| 37 | madvise(MADV_SEQUENTIAL) on remaining np.memmap sites: xcorr_py, proj_ra2ll_fast, SAT_baseline_py | optimization | few s/case under contention |
| 38 | gmt_surface_py: native pixel-reg mode + Briggs sub-cell constraints | 3 | unblocks ~25-50 s/case when wired |
| 39 | Wire make_los_py (geocode.csh:77, :139) + phasediff_py (intf.csh, RS2-short-baseline) | 1 | ~5 s/case |
| 40 | Refactor _jit_kernels_sat.py and SAT_baseline_py to import from utils/vector.py | cleanup | ~300 lines consolidated; no perf delta |
| 41 | Port align_tops.csh to Python (removes 6 csh call sites from p2p_stages.py) | 3 | enables S1 TOPS Phase 3 |
| 42 | Port intf + filter binaries (finish Mira #28's work; long-baseline + OMP perf) | C-binary | ~3-5 s/case |
| 43 | Port snaphu.csh + snaphu_interp.csh wrappers | 3 | cleanup |
| 44 | In-memory chain in dem2topo_ra (no intermediate .grd writes between gmt cmds) | medium | 5-10 s/case |
| 45 | Port pre_proc per SAT family (huge — S1 TOPS first) | Phase 6 | months each |

## 9. GMT subprocess → in-process port roadmap

The full strict-single-thread sweep (2026-05-21, 21/21 PASS after Mira #15-#17
fixes) shows the Python pipeline is bit-identical to csh but ~1× speed at
serial. The 50% pipeline cost concentrated in `dem2topo_ra` is mostly
**single-thread GMT subprocesses** that the Python framework calls but
doesn't replace. The path to real speedup goes through replacing those
subprocess calls with in-process numpy / numba / GPU.

### Replacement value matrix

| GMT command | numpy | numba JIT | numba prange | GPU | Best stop |
|---|---|---|---|---|---|
| `grdmath` simple (ADD/MUL/FLIPUD) | ✅ instant | — | — | — | **numpy** (SIMD-vectorized already) |
| `grd2xyz` / `xyz2grd` | ✅ instant | — | — | — | **numpy** (I/O-bound) |
| `grdcut` | ✅ instant | — | — | — | **numpy** (lazy slice) |
| `gmtconvert` (column reorder) | ✅ instant | — | — | — | **numpy** |
| `blockmedian` | 1× | 2-3× | 4-7× | 10-30× | numba prange viable |
| `grdsample` (bilinear) | 1× | 1.5× | 3-5× | 20-50× | numpy for small / GPU for big |
| `grdtrack -nl` | 1× (done by Mira #11) | 2× | 5-10× | 30-100× | numpy now, GPU for batch |
| **`gmt surface`** (continuous-curvature spline) | ⚠ 1× (slow PDE) | 5-10× | **20-40×** | **100-500×** | **GPU is the natural ceiling** |

### Why `gmt surface` is the keystone

It's a multigrid PDE relaxation: 9-point stencil sweep, embarrassingly parallel
per-cell within a Jacobi iteration. Appears 3× per case (raln, ralt, topo_ra).
On NISAR it's ~50 s per call. Porting to `numba @njit(parallel=True) + prange`
should yield ~5-10× speedup on 8 cores; GPU (`@cuda.jit` or `cupy`) goes 100×.

Until `gmt surface` is replaced, the pipeline is fundamentally bottlenecked at
~50 s/case on dem2topo_ra regardless of how much we parallelize the Numba ports.

### Why other commands aren't worth deeper porting

- `grdmath ADD/MUL/SUB/FLIPUD` etc. are at memory bandwidth via numpy. Numba
  can't beat numpy on SIMD-vectorized array ops; gain is zero.
- `grd2xyz` and `xyz2grd` are pure I/O — savings come from killing the
  subprocess + ASCII round-trip, not from compute parallelism.
- `grdcut` is O(1) lazy slicing in xarray; no compute to parallelize.

Conclusion: for these commands, **stop at numpy**. Don't waste numba effort.

### Roadmap (ordered by ROI)

**Tier 1 — bulk easy wins (1 week, no Numba/GPU)**
- Replace `grd2xyz`, `xyz2grd`, `grdcut`, `grdmath`, `gmtconvert` with
  numpy/xarray calls in `dem2topo_ra` and `geocode`.
- Saves ~5-15 s/case on overhead + ASCII round-trips.
- Risk: low (each replacement is a numerical no-op).
- **Tier-1 dependency (LANDED 2026-05-21):** `utils/gmt_grd_io.py`
  provides `write_gmt_grd()`, a pure-Python (numpy + netCDF4) writer
  that emits the canonical GMT netCDF flavor. Required because xarray's
  default `to_netcdf()` writes a netCDF GMT *can* open but with missing
  `actual_range` (grdinfo reports `v_min=0 v_max=0`) and missing
  `node_offset` (pixel-registered grids get silently half-cell-shifted
  by `grdcut`). Replacements for `grdmath`, `grdcut`, `xyz2grd` that
  produce `.grd` outputs must route through `write_gmt_grd`, not
  `xr.Dataset.to_netcdf`. See parity tests in
  `bin_py/tests/test_gmt_grd_io.py`.

### GMT netCDF attribute spec (required for downstream gmt modules)

What `write_gmt_grd` (and any future GMT-compatible Python writer) must
emit so `grdinfo`, `grdmath`, `grdcut`, `grdtrack`, `grd2xyz`, `xyz2grd`
all behave identically to what they would on a native GMT-written file.
Derived by `ncdump -h` on a sample of GMT-written files (GMT 4.5.7,
6.3.0, 6.4.0) shipped with this repo.

**Global attributes**
| Attribute | Required? | Value | Why GMT needs it |
|---|---|---|---|
| `Conventions` | yes | `"CF-1.7"` (modern) or `"COARDS/CF-1.0"` (legacy) | reader dispatch — without it, GMT falls back to no-conventions mode |
| `title` | recommended | free string | `grdinfo: Title:` field |
| `history` | recommended | free string (typically the command line) | `grdinfo: Command:` field |
| `description` | recommended | free string (may be `""`) | reserved by GMT 6+ |
| `GMT_version` | recommended | free string | provenance; reported by `grdinfo` |
| `node_offset` | **REQUIRED FOR PIXEL** | int32 `1` | pixel-vs-gridline registration switch. Omit for gridline (default). Silent half-cell shift in `grdcut` etc. if missing on a pixel-reg grid. |

**Coordinate variables (`x`/`y` for Cartesian, `lon`/`lat` for geographic)**
| Attribute | Required? | Value | Why |
|---|---|---|---|
| dtype | yes | `float64` (`f8`) | GMT's reader assumes double-precision coords |
| `long_name` | recommended | `"x"`/`"y"`/`"longitude"`/`"latitude"` | CF convention; reported by `grdinfo` |
| `units` | **REQUIRED FOR GEOGRAPHIC** | `"degrees_east"` / `"degrees_north"` | switches `grdinfo` to "Geographic grid" mode. Without it, lon/lat grids are reported as Cartesian. |
| `axis` | recommended | `"X"` / `"Y"` | CF axis hint |
| `actual_range` | strongly recommended | `[min, max]` float64 | propagated by `grdmath`; without it some chains lose track of bounds |

**Data variable (`z`)**
| Attribute | Required? | Value | Why |
|---|---|---|---|
| dtype | yes | `float32` (`f4`) | this is GMT's `nf` format — what `grdmath`, `xyz2grd`, etc. always emit |
| `long_name` | recommended | `"z"` | CF convention |
| `_FillValue` | yes | float32 NaN (`NaNf`) | GMT marks missing data with NaN. Other sentinels break `grdmath` and `grdfill` |
| `actual_range` | **REQUIRED** | `[min, max]` float64 over non-NaN values | without this, `grdinfo` reports `v_min=0 v_max=0` for the data variable. Silent failure mode. |

**Dimension order / orientation**
- `z(y, x)` — y is the slowest dimension (rows), x is the fastest (cols).
- y values MUST be monotonically ASCENDING in the file. Row 0 is at
  `y_min`. (GMT's `grd2xyz` then emits the file top-down — flipping
  internally — but on disk the storage is y-ascending.)
- x values MUST be monotonically ascending in the file.
- Spacing MUST be uniform along each axis. GMT tolerates ~1e-4
  relative non-uniformity; `write_gmt_grd` enforces 1e-6.

**Tier 2 — medium kernels (2-3 weeks, numba prange)**
- Port `blockmedian`, `grdsample`, `grdtrack` to numba parallel kernels.
- Saves ~5-10 s/case in compute.
- Risk: medium (parity tests against gmt versions on real data).

**Tier 3 — gmt surface in numba (1-2 months)**
- Implement multigrid continuous-curvature spline solver in
  `@njit(parallel=True)` with prange over rows. Reference: GMT's
  `src/surface.c` (Smith & Wessel 1990 algorithm).
- Saves ~30-60 s/case (3× surface calls per pipeline).
- Risk: high (algorithm verification — must match gmt surface within
  iteration-count tolerance).

**Tier 4 — GPU (3-6 months, optional)**
- Port the heavy kernels (`surface`, `blockmedian`, `grdtrack`) to
  cupy / `@cuda.jit`.
- Saves another 5-50× on kernel work alone.
- ROI condition: only worthwhile if (a) machine has GPU, (b) data is
  large enough to amortize transfer cost (NISAR-scale yes, RS2-scale
  no), (c) running many cases (sweep / SBAS workloads).
- Risk: medium (cuda numerics ≠ CPU numerics for floats).

### Honest end-game

After Tier 3 is done, dem2topo_ra wall time drops from ~50 s to ~10-15 s.
Pipeline-level speedup vs current strict-serial Python: **2-3×** on big cases.
Pipeline-level vs csh: **3-5× faster** at single-thread, **8-15× faster**
at NUMBA_NUM_THREADS=8.

Tier 4 (GPU) is mostly for production SBAS / batch processing, not
single-pair P2P. Single-case use will hit Amdahl's law on the C bits
(`intf`, `filter`, `snaphu`) that aren't being ported.

## 8. Open questions

- **SBAS test fixture:** does `topex.ucsd.edu/gmtsar/tar/` host a multi-pair
  time-series example, or do we curate one? Phase 4 blocks on this.
- **Parallelism budget:** should phase 2 `*_parallel` utilities respect the same
  `MAX_PARALLEL` env var the test sweep uses, or have their own?
- **csh deprecation horizon:** is the long-term goal to remove the csh shell-out
  shims entirely, or keep them as fallback? Affects how aggressively phase 3
  rewrites internals.
