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

## 9c. Status snapshot 2026-05-22 (post-v2.1.9 evening)

### Session arc this day

```
Tags landed today: v2.0.2 → v2.1.9  (17 patches/minors)
  v2.0.2  snaphu wrappers (Mira #43)
  v2.0.3  phasediff_py + make_los_py wire (Mira #39)
  v2.0.4  fitoffset.csh fix (Wei audit)
  v2.0.5  align_tops.csh ported (Mira #41, byte-id Greece F2)
  v2.0.6  gmt_surface_py FMG+aniso+Briggs wire env-gated (Mira #38)
  v2.0.7  SAT_llt2rat constants → utils/vector.py (Mira #46)
  v2.0.8  merge_unwrap_geocode_tops snaphu fix + awk-int (Mira #49)
  v2.0.9  iono env-gate + scipy gauss opt-in (Mira #48)
  v2.1.0  MILESTONE — 9/9 SAT --fast pass, cumulative 1.22× py vs csh
          Iris's --unit/--smart_fast/--sample/blessed tier system landed
  v2.1.1  touched_to_cases.py rules extended (Mira #51)
  v2.1.2  xcorr C-parity test opt-in (--unit drops 21→3min)
  v2.1.3  stage-cache infrastructure (default OFF, 25 tests pass)
  v2.1.4  Rule 10 — port C algorithm verbatim first
  v2.1.5  Rule 10 carve-out — bit-id AND faster ports keep as-is
  v2.1.6  blockmedian_py wrap (RED trap removed, Mira #56)
  v2.1.7  gmt grdsample port — byte-id + 1.95× faster (Mira #54)
  v2.1.8  gmt surface FAITHFUL port — byte-id, but 1.9-4× SLOWER (Mira #52)
  v2.1.9  gmt grdfilter port — byte-id + 6× faster (Mira #55)
```

### What's wired in production (default ON)

```
✓ gmt grdmath FLIPUD/MUL/ADD/SUB (Miras #30/#36)         in-process numpy
✓ gmt grdtrack bilinear (Mira #11)                       proj_ra2ll_fast
✓ gmt gmtconvert (Mira #19)                              gmt_inproc.py
✓ snaphu / snaphu_interp wrappers (Mira #43)             utils/snaphu.py
✓ align_tops.csh port (Mira #41)                         utils/align_tops
✓ phasediff_py + make_los_py (Mira #39)                  intf, geocode
✓ iono Python wrapper (default uses gmt grdfilter)       utils/estimate_ionospheric_phase
✓ merge_unwrap_geocode_tops port (Mira #49)              utils/merge_unwrap_geocode_tops
✓ SAT_llt2rat constants centralized (Mira #46)           via utils/vector.py
✓ blockmedian CLI wrapper (Mira #56)                     bin_py/blockmedian_py
```

### What's ported but NOT yet wired (committed v2.1.X)

```
○ gmt_grdsample_py (v2.1.7)        utils/gmt_grdsample_py.py — byte-id + 1.95× faster
                                     Wire target: 5 sites in snaphu.py + p2p_stages.py
                                     Status: ready, awaits wire-in Mira
                                     
○ gmt_grdfilter_py (v2.1.9)        utils/gmt_grdfilter_py.py — byte-id + 6× faster
                                     Wired into iono path env-gated; default still gmt subprocess
                                     because iono not in regression sweep
                                     
○ gmt_surface_py (v2.1.8)          utils/gmt_surface_py.py — byte-id, but 1.9-4× SLOWER
                                     GMTSAR_SURFACE_INPROC=1 to enable; default OFF
                                     Awaits Mira #60 optimization pass
                                     
○ stage-cache (v2.1.3)              tests/stage_cache.py — GMTSAR_STAGE_CACHE=1 to enable
                                     Default OFF until multi-case parity verification
                                     
○ scipy.gauss opt-in (deprecated)   utils/estimate_ionospheric_phase
                                     Mira #55's grdfilter port replaces it byte-id
                                     Wire confirmed; legacy scipy code deleted
```

### Active Miras (2026-05-22 evening)

```
🏃 Mira #44  in-memory chain in dem2topo_ra
             Eliminates intermediate .grd I/O between adjacent in-process ops
             Target: 5-10s/case savings
             Worktree-isolated
             
🏃 Mira #60  perf-tune gmt_surface_py to match-or-beat gmt C single-thread
             Cache-aware tiling, float32 precision, SIMD-friendly stencil
             Target: 6601×4801 ≤ gmt's 9.49s
             Worktree-isolated
```

### Roadmap — what's still needed to port

#### Tier P — Ports that LOSE to gmt C (need optimization)

```
1. gmt_surface_py (v2.1.8)
   Status: faithful but 1.9-4× slower than gmt C single-thread
   Mira #60 optimizing now
   IF can't beat gmt at strict single-thread: document gap, use
   per-grid-size dispatch (small grids = py, big grids = gmt subprocess)
```

#### Tier W — Ports ready to wire (byte-id + faster)

```
2. gmt_grdsample_py wire-in (small Mira mission)
   5 sites in snaphu.py + p2p_stages.py
   Replaces ~5 gmt grdsample subprocess calls per case
   Estimated 30-min Mira mission
   
3. gmt_grdfilter_py default-on for iono (when iono gets regression coverage)
   Currently GMTSAR_IONO_GAUSS_PY=1 enables py path
   Default flip blocked on: no test case has correct_iono=1
   Need test fixture with iono enabled before flipping default
   
4. gmt_surface_py default-on for small grids
   Currently GMTSAR_SURFACE_INPROC=0 default
   Per-grid-size dispatch: if n_nodes < 4M, use py; else gmt
   Estimated 1-day Mira mission (depends on Mira #60 result)
```

#### Tier R — Rule 10 cleanup (YELLOW items from Mira #53 audit)

```
5. phasediff_py long-baseline spline correction
   Currently NotImplementedError for baseline > 1000m
   Port phasediff.c lines ~470-540 (Lindsey 2015 spline range-shift)
   Need ALOS-2 wide-swath or TanDEM-X test data
   Estimated 1-week Mira mission
   
6. scipy.gauss opt-in deletion confirmation
   Mira #55 already wired gmt_grdfilter_py into iono
   Verify no callers remain using the old scipy path
   Estimated 30 min audit
```

#### Tier C — Big-effort C ports (deferred)

```
7. pre_proc per SAT family port (huge)
   ALOS, ALOS2, CSK, ENVI, ERS, RS2, S1, TSX = 7-8 families
   Each ~2-4 weeks (read SAT-specific raw → SLC focusing C code)
   Total ~3-6 months
   Biggest single perf gain remaining (30-50% wall reduction per case)
   
8. intf / filter C binaries port
   Medium effort: ~2-4 weeks total
   Each ~5-10s/case
   
9. snaphu C binary (third-party, 30k LOC)
   NOT recommended to port — well-tested, optimized, complex
   Keep subprocess wrapper indefinitely
```

#### Tier I — Infrastructure (test system, in-memory chain)

```
10. In-memory chain in dem2topo_ra (Mira #44 active)
    Removes ~5-10 intermediate .grd writes per case
    
11. In-memory chain in geocode (similar pattern, future Mira)
    
12. Stage-cache production wire (when default-on validated)
    
13. CI integration (GitHub Actions / similar)
    Auto-run --unit + --smart_fast on every PR
    Estimated 1 day
    
14. Add iono-enabled test fixture (correct_iono=1)
    Unblocks default-on iono port
    
15. Wire phasediff_py long-baseline (after Tier R #5 lands)
```

### Perf summary (cumulative, single-thread)

```
v2.0.0 baseline (mixed vintage):   1.04× py vs csh (essentially parity)
v2.0.1 (madvise NFS fix):          all 9 SAT py > csh; CSK_RAW/TSX flipped
v2.1.0 milestone:                  cumulative 1.22× py vs csh on --fast 9 SAT

Expected after Tier W (wire-in) lands:
  + Mira #44 in-memory chain:    5-10s/case
  + grdsample wire-in:           5-10× faster on 5 sites per case
  + grdfilter default-on (iono): only when iono enabled, future
  Estimated cumulative: 1.3-1.5× py vs csh on --fast
  
Expected after Tier P (surface optimization) lands:
  + If Mira #60 beats gmt:       50-100s/case on big-grid cases
  Estimated cumulative: 1.5-2.0× py vs csh on --fast

Expected after Tier C (pre_proc port):
  + Per-SAT-family wins as each lands
  Estimated 30-50% wall reduction per case for that SAT family
  Time horizon: 6-12 months
```

### Project rules timeline

```
Rule 8 (merge gate): codified after Mira #43 NISAR stale-oracle incident
Rule 8.8 (path-exercising smoke): codified after gmt_surface_py wire-in 
         smoke fell through to subprocess on RS2 (anisotropic case)
Rule 9 (no writes to csh_test/): codified after sweep-script bugs
Rule 10 (port C verbatim): codified 2026-05-22 from gmt_surface_py Jacobi shortcut
Rule 10 carve-out (bit-id + faster keep as-is): refined same day
Rule 11 (every bugfix -> regression test): codified 2026-05-22 (v2.1.18)
```

### Campaign paused 2026-05-22 (resume here)

```
HEAD at pause: v2.1.21 (8fbf892)
--fast (6-case tier): 5/6 reported green (RS2, CSK_RAW, ERS, S1A_Greece,
  ALOS_haiti all pass); ALOS_haiti and ALOS_Baja_EQ py-side both finished
  clean, ALOS_Baja_EQ comparison just didn't make the report window —
  re-run --fast first thing on resume to get a clean 6/6 baseline.

Landed since v2.1.18:
  v2.1.19 - grdsample default ON (numba NaN-gather fix, Mira #65)
  v2.1.20 - grdfill wired into dem2topo_ra, default OFF (pixel-reg gap), Mira #67
  v2.1.21 - SHA/vintage sidecar tracking for sweep reconciliation, Mira #69
  267 passed / 11 skipped on full bin_py/tests/ (excl. surface, ~3min)

Still open / lost work to re-dispatch on resume:
  - GMTSAR_SURFACE_INPROC default OFF: gcd(n_columns-1,n_rows-1)==1 bug
    (ENVI 5191x7579, TSX 9440x6937 -> wrong fixed point, no multigrid
    hierarchy). Mira #68 was fixing this, hit session limit, no
    worktree/result survived -> re-dispatch from scratch.
  - GMTSAR_GRDFILL_PY default OFF: _bcr_bicubic_sample hardcodes
    in_off=0.0, breaks on pixel-reg donor grids ("donor grid does not
    cover query x range"). See AUDIT_grdfill_wirein_mira_2026-05-22.md
    for fix path. Mira #70 was fixing this, hit session limit, lost.
  - xyz2grd port: Mira #71 hit session limit before starting, lost.
  - Stage cache: architecturally broken (AUDIT_stage_cache_mira57.md),
    needs redesign mission (fingerprint post-stage outputs instead of
    raw/ mutate-restore). Not yet dispatched.
  - GMTSAR_IONO_GAUSS_PY: still blocked on no test case having
    correct_iono=1.
  - GMTSAR_DEM2TOPO_INMEM_CHAIN: depends on SURFACE_INPROC being safe.

On resume: re-run --fast for a clean baseline, then re-dispatch the
3 lost missions (surface gcd=1, grdfill pixel-reg, xyz2grd) in
worktrees per the standing 3-concurrent-Mira discipline.
```
