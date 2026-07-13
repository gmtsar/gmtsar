# Pathway forward — what's ported, what's not, and why

## Known bug, not yet fixed

- **`utils/tkGUI.gmtsar:86,97`**: `self.gmtsarPath` silently defaults to
  the literal string `'python'` when `p2p_processing` isn't already on
  `$PATH` at GUI launch time, and that value gets prepended into
  `os.environ['PATH']` unconditionally — a silent fallback (violates the
  project's no-silent-fallback discipline). If a user launches the GUI
  from a shell without `$GMTSAR/bin` on PATH, every Config/p2p_processing
  button click fails with an unhelpful subprocess error. Found 2026-07-12
  during a live GUI verification pass (not synthetic — reproduced by
  launching without the PATH export). Cheap fix: fail loud (raise/log a
  clear error) instead of silently substituting a garbage path.
- **`install.sh --python`'s `pip install --upgrade -r requirements.txt`
  is unsafe against a live/shared conda env — incident, found AND
  recovered 2026-07-13.** During a from-scratch new-user onboarding
  test, running `install.sh --conda --python --build` against the same
  `gmtsar` conda env that other processes had open (background test
  sweeps using numba-JIT kernels) caused a partial package upgrade —
  `llvmlite` got bumped to an incompatible version while `numba` didn't
  finish reinstalling (NFS "device or resource busy" mid-swap), breaking
  numba JIT compilation for every kernel in the env. This correctly
  crashed one in-flight sweep (`ALOS_haiti`) — a real, honestly-reported
  failure caused by env fallout, not a code bug; it was not chased as
  one. **Recovered** with a targeted, minimal fix once no other process
  had the env open: `pip install 'numba==0.65.1'` (no `--upgrade`, no
  blanket `-r requirements.txt`), which let pip's resolver pull the one
  correct matching `llvmlite` (0.47.0, satisfying numba 0.65.1's
  `<0.48,>=0.47.0dev0` constraint) without touching any other package.
  Verified via `bin_py/tests/test_gmt_blockmean_py.py` +
  `test_vector.py` (40/40 pass) and a fresh `ALOS_haiti` re-run.
  **Root-cause fix still open**: `install.sh --python` itself still uses
  `--upgrade`, which can repeat this exact failure mode against any
  live/shared env. Fix candidates: drop `--upgrade` (only install
  missing packages, don't touch already-satisfied ones), or add an
  explicit warning/check that the target env has no other attached
  processes before installing.

Living roadmap. Read this before re-deriving "what's left to port" from
scratch — this survey (2026-07, HEAD v2.5.6) already did that work and
cross-checked it against the actual code, not just prior release notes
(several of which turned out to disagree with each other and with the
current code — see the surface entry below for the cautionary tale).

**Governing principle**: a module stays C because a Python port is
judged unlikely to beat it (measured, or reasoned from its nature — e.g.
I/O-bound format parsing), not because "it already works so we didn't
try." Every entry below states which is true.

## Wiring-status ledger (project_rules.md Rule 13)

"Ported" and "wired ON by default" are different states. Every module
below is tagged with exactly one:

- **[1-ON]** wired ON by default, both gates passed and reviewed.
- **[2-OFF-pending]** ported, parity proven, gate-2 evidence exists
  (win or tie) — not yet promoted, pending a full-sweep review.
- **[3-OFF-lost]** ported, parity proven, gate-2 **failed** — a real,
  measured loss, correctly left off. Not a gap.
- **[4-partial]** ported on a subset only, no dispatcher/call site wired.
- **[5-none]** never attempted — split into worth-it / not-worth-it below.

| Module | State | Evidence | Dispatcher |
|---|---|---|---|
| `xcorr_py` | [1-ON] | ~30x faster (2026-07-12); **flagged 2026-07-13 for re-check under a quiet system, see Rule 12c and "Tried, kept on C" below** — real pipeline's own C-binary timer shows a much smaller gap on RS2 | `p2p_stages.py`, unconditional |
| `resamp_py` | [1-ON] | ~1.3x faster, byte-identical (re-wired 2026-07-12, was OFF-lost as v2) | `p2p_stages.py`, unconditional |
| `SAT_llt2rat_py_v2` | [1-ON] | +7.6% vs v1, ties C, no NFS instability (verified 2026-07-12) | `install.sh` symlink, unconditional |
| `gmt_surface_py` | [1-ON, correctness only] | C 269s vs py 412s — C faster; wired for bit-parity, not speed | `dem2topo_ra`/`align_tops`/`proj_ll2ra`/`tide_correction` |
| `gmt_grdmath_py` | [1-ON, selective] | 14.2x per-call (isolated MUL sites only) | 16 sites, see release_notes_v2.5.0 |
| `gmt_grdcut_py` | [1-ON] | 1.2-4.2x depending on call site | 19 sites |
| `gmt_grdsample_py` | [1-ON] | parity per-call; 1.7x in warm multi-call reuse only | `grdsample_wrapper.py` |
| `phasediff_py`, `phasefilt_py`, `gmt_grdfill_py`, `align_tops`, `make_los_py` | [1-ON, audit gap] | correctness evidence only, **no isolated gate-2 timing exists** | various, see "Tried, kept on C" below |
| `make_slc_s1a_py` | [1-ON] | +1.4-1.8x, byte-identical; confirmed end-to-end on real S1A_SLC_TOPS_Greece sweep (10/10 SUCCESS, 2026-07-13) | `pre_proc`, `GMTSAR_S1A_PREPROC_PY=1` |
| `make_slc_nsr_py` | [1-ON] | +19x, byte-identical; confirmed end-to-end on real NISAR_Ethiopia sweep (6/6 SUCCESS, csh 431s->py 152s, 2026-07-13) — found+fixed a real `_get_config` quote-stripping bug along the way, see below | `pre_proc_nsr`, `GMTSAR_NSR_PREPROC_PY=1` |
| `gmt_blockmean_py` | [2-OFF-pending] | +3.7-19.3x, tolerance-equal (not byte-identical, see below) | `dem2topo_ra`, `GMTSAR_BLOCKMEAN_PY=0` |
| `make_slc_rs2_py` | [1-ON, Rule 13a] | ~1.3x slower individually; wired anyway (deployment simplicity, pre_proc ~7.8% of total time); confirmed end-to-end (RS2_SLC_Hawaii 6/6 SUCCESS, 1.96x case-level, 2026-07-13) | `pre_proc`, `GMTSAR_RS2_PREPROC_PY=1` |
| `make_slc_tsx_py` | [1-ON, Rule 13a] | slower individually (numpy import tax); wired anyway; confirmed end-to-end (TSX_SLC_Hawaii 6/6 SUCCESS, 1.19x case-level, 2026-07-13) | `pre_proc`/`gmtsar_lib.py`, `GMTSAR_TSX_PREPROC_PY=1` |
| `make_slc_csk_py` | [1-ON, Rule 13a] | ~1.3-2x slower individually; wired anyway; confirmed end-to-end (CSK_SLC_Italy 6/6 SUCCESS, 1.04x case-level, 2026-07-13) | `pre_proc`, `GMTSAR_CSK_MAKE_SLC_PY=1` |
| `make_slc_csk2_py` | [3-OFF-lost] | ~4-5x slower, byte-identical | `pre_proc`, `GMTSAR_CSK_PREPROC_PY=0` |
| `gmt_triangulate_py` | [3-OFF-lost] | 1.4-9x slower (Qhull vs GMT's linked Shewchuk Triangle) | `dem2topo_ra`, `GMTSAR_TRIANGULATE_PY=0` |
| `ALOS_pre_process_py` | [4-partial] | IMG-parsing subset byte-identical, +2.1x — LED/orbit/Doppler not ported | none — parity is partial |
| `SAT_llt2rat_py` (v1) | archived, superseded by v2 | byte-identical, but v2 wins on speed+stability | `bin_py/archive/` |
| `resamp_py_v2` | archived, superseded by v1 | unstable NFS/numba cache, only tied with C at best | `bin_py/archive/` |
| `SAT_look` | [5-none] | still C, `calc_look_vector` calls it directly | n/a |
| `iono_gauss` | ported, opt-in correctly | fails gate 1 by design (2% divergence allowed) | `GMTSAR_IONO_GAUSS_PY` unset |
| `gmt triangulate`(via triangulate_py, see above), `grdedit`, `trend2d`, `grdlandmask`, ~60 other `gmt` subcommands | [5-none] | see "Never attempted, not worth it" below | n/a |
| SAR preprocessors not yet attempted (`make_slc_gf3/lt1`, `ENVI_preproc`, `ERS_preproc`, `calc_dop_orb`, `extend_orbit`, `update_PRM`) | [5-none] | no cached test fixture, or disproportionate complexity | n/a |
| `esarp.c` (real SAR focusing DSP) | [5-none, highest-leverage if revisited] | never scoped — see "Deferred by design" below | n/a |

## Done

- 1:1 utility coverage of the legacy csh codebase (every csh script has a
  Python counterpart), merged upstream via PR #1114.
- 13 compute-kernel dispatchers wired on by default at their primary call
  sites: cross-correlation (`xcorr_py`), phase difference (`phasediff_py`,
  baseline ≤1000m only — longer baselines fall back to C), resampling
  (`resamp_py`), `SAT_llt2rat` (unconditional, no C fallback), block median
  (`gmt_blockmedian_py`), phase filter (`phasefilt_py`), grdmath
  (`gmt_grdmath_py`, selective — see below), grdsample, grdcut, grdfill,
  align_tops, make_los, iono (the grdmath/grdfilter/surface subprocess
  chain only — see corrections below).
- **Corrections from a 2026-07-12 audit** (do not repeat these errors):
  `SAT_look` is **still C** — `utils/calc_look_vector` calls the C binary
  directly, unconditionally; no `SAT_look_py` exists. `iono_gauss` (the
  scipy.ndimage Gaussian substitution, distinct from the iono grdmath
  chain above) is **opt-in only** (`GMTSAR_IONO_GAUSS_PY` unset by
  default) — correctly so, its own test asserts up to 2% divergence from
  C, so it fails gate 1 (bit-identical) by design and must stay opt-in.
  `merge_tops` does not exist as a file/dispatcher; the real merge step is
  `merge_unwrap_geocode_tops`, whose sub-calls (grdmath/grdsample/grdcut)
  are already covered above.
- **Gate-2 (speed) audit gap**: of the 13 kernels above, only
  `gmt_blockmedian_py` (~10% faster, single-site number), `gmt_grdmath_py`
  (14.2x per-call on isolated MUL sites), `gmt_grdcut_py` (1.2-4.2x
  depending on call site), and `gmt_grdsample_py` (parity per-invocation,
  1.7x in warm multi-call reuse) have **any** isolated timing evidence.
  `phasediff_py`, `phasefilt_py`, `gmt_grdfill_py`, `align_tops`,
  `make_los_py` are wired on by **correctness evidence only** — no
  standalone C-vs-Python timing exists yet. None show evidence of
  *failing* gate 2 (unlike `resamp_py`, below), but "no evidence of
  failing" is not the same as "passes" — this is an honest gap, not a
  verified pass.
- `topo_interp_mode=1` (triangulation fast-path for `dem2topo_ra`):
  16/21 cases PASS, 2.04x aggregate speedup, v2.5.6 fixed a real
  masked-cell/`phasediff`-segfault bug. Opt-in, not default — see the
  talk deck (`slides/20260722_python_framework_gui/`) for the honestly
  reported accuracy tradeoff on the 5 non-passing cases.

## Tried, kept on C — documented, not a gap

- **`resamp_py` / `xcorr_py`, resolved 2026-07-12, `xcorr_py` re-flagged
  2026-07-13** (fresh, isolated, single-core-pinned, real RS2_SLC_Hawaii
  data, parity-checked byte-identical to C for both): `xcorr_py` is
  genuinely faster — C's `xcorr.c` re-builds a GMT FFT plan on every one
  of 1000 calls (91% CPU but 409s of *system* time out of 651s user —
  plan/malloc churn, not compute), a real, reproducible architectural
  difference. **But the exact ~30x figure is not yet trustworthy as a
  clean number**: a 2026-07-13 re-measurement under `load average: 21`
  (contended by two orphaned processes from an earlier, already-
  completed Mira agent that never got cleaned up, plus another user's
  job) gave C `xcorr` 1054s — while the SAME C binary's own internal
  timer, from a real pipeline sweep run minutes earlier on the identical
  case/parameters, printed `elapsed time: 121.5s`. That's a >8x
  discrepancy on the C side alone, meaning both the original 2026-07-12
  measurement and the 2026-07-13 re-check may be contaminated by system
  load, not a clean single-thread number. Per Rule 12c: **a from-scratch
  re-measurement under a quiet system (check `uptime` first) is needed
  before citing a specific multiplier again.** What's solid: the
  architectural reason (FFT plan rebuild per call) and the direction
  (faster) — not yet the exact number.
  This was a split story at first: `bin/resamp_py` had been symlinked to
  a since-archived alternate implementation (the de facto wired default
  at the time, contradicting the old rc2 note which had benchmarked the
  unwired plain `resamp_py`). That alternate's timing was **unstable
  (10-58s)** because its numba on-disk JIT cache defaulted to
  `bin_py/__pycache__`, which lives on NFS — synchronous NFS stat/open
  round-trips during cache validation. Pointing `NUMBA_CACHE_DIR` at
  local disk stabilized it to ~11-12s, roughly **tied** with C
  (10.9-13.3s) — not a clear win. Plain `resamp_py` was the actually-faster
  variant (~1.3x, byte-identical) and wasn't what was deployed.
  **Fixed 2026-07-12**: `install.sh` and the live `bin/resamp_py` symlink
  now point at the single production `resamp_py` (no version suffix —
  production code shouldn't carry one; `SAT_llt2rat_py`/`_v2` still does
  and is a candidate for the same cleanup, not yet done, out of scope
  here). `resamp_py` can now be cited as a consistent ~1.3x speedup,
  byte-identical to C. The old alternate's NFS-numba-cache instability is
  no longer reachable via the default wiring; that file was **moved to
  `bin_py/archive/resamp_py_v2`** (not deleted — real, documented work,
  archive-only, not production) so it can't be mistaken for the current
  baseline. See `bin_py/archive/README.md` before reviving it.
- **`gmt surface` (biharmonic spline fit)**: a bit-faithful numba/Cython
  port (`gmt_surface_py`) exists and is wired ON by default at most call
  sites (`dem2topo_ra`, `align_tops`, `proj_ll2ra`, `tide_correction`) —
  **for correctness/bit-parity, not speed**. Measured (v2.5.5): C 269s vs.
  Python 412s single-threaded — C is faster. Two parallelization attempts
  (red-black SOR, domain-decomposition prototypes in `docs/experiments/`)
  both failed: the kernel is memory-bandwidth-bound, not compute-bound, so
  more threads don't help. This is the single clearest "we tried, we
  measured, we couldn't beat it" case in the whole framework.
  - **Caution for future readers**: earlier release notes (v2.4.0) and an
    even-earlier session memory each stated a *different* reason for any
    non-default surface behavior (one claimed near-parity speed, one
    claimed a 0.46m accuracy divergence at CSK scale). Neither matches the
    current code or the later, more careful v2.5.5 measurement. Always
    verify against the current code (`grep GMTSAR_SURFACE_INPROC utils/`)
    and the most recent release note, not the first one you find.
  - **Narrower, separate exception**: `proj_ra2ll`'s raln/ralt construction
    uses C surface by default via its own gate (`GMTSAR_PROJ_SURFACE_PY`,
    default OFF) — a real, different, already-fixed bug (v2.5.4): the
    Python port's ~1e-5° edge roundoff shifted the geocoded region by a
    full coarse-lattice cell on `S1A_SLC_TOPS_Greece`/`TOPS_LA`. Do not
    conflate this with the general surface-speed story above.
- **`snaphu` (phase unwrapping)**: a full numba/Cython solver port exists
  (`bin_py/snaphu_py/`) but is not production-ready — `docs/dev_notes/
  NOTES_SNAPHU_FIX.md` documents specific unresolved bugs (a min-cost-flow
  pred-chain cycle hang on 30x30 synthetic input, an 8x10 numba-only
  infinite hang, a result divergence from the scalar oracle on some 5x7
  seeds). Never reached real data — synthetic tests fail first. The
  default Python path (`utils/snaphu.py`) does I/O/staging only; the
  actual unwrap still calls the C `snaphu` binary. Low priority to unblock
  regardless: snaphu is ~0.3% of pipeline wall-time.

## Attempted 2026-07-12: gmt_triangulate_py — the predicted win that wasn't

Ported (`utils/gmt_triangulate_py.py`, `scipy.spatial.Delaunay`/Qhull +
barycentric interpolation), wired at both `dem2topo_ra` call sites behind
`GMTSAR_TRIANGULATE_PY`, default OFF. This was the one candidate on the
list flagged as "genuine compute, most likely real win" — turned out to
be the opposite.

**Parity**: pass on typical scale (RS2_SLC_Hawaii, 964,812 pts — bit-
identical, 0 mismatches). One documented gap at large scale
(ALOS4_Pinon, 6.16M pts): 10 of 29.3M grid nodes diverge (max diff 12.2),
traced to near-degenerate/near-cocircular point quads where Qhull and
GMT's linked Shewchuk Triangle library pick a different diagonal — a
genuine, rare (~3.4e-7 of nodes) algorithmic tie-break, not roundoff.

**Speed: fails gate 2**, consistently, 1.4-9x **slower**. Root cause:
`scipy.spatial.Delaunay`'s build step alone is ~9.4-9.9s, an opaque Qhull
C call with no numpy vectorization angle. Tried qhull_options tuning (no
improvement) and `matplotlib.tri.Triangulation` (6.9s, still ~3x slower).
GMT's C reference already uses the field-optimal library for this exact
operation — general-purpose Qhull has no answer for it. Wired but kept
OFF; only a direct C-extension binding to Shewchuk's Triangle (or GMT's
own routine) could plausibly close this, and that needs explicit
sign-off before attempting.

**Lesson**: "genuine compute" was the wrong reason to expect a win here —
the C reference wasn't hand-rolled or naive, it was already using the
best-in-class library. The earlier framing conflated "compute-heavy" with
"beatable"; they're not the same thing.

## Attempted 2026-07-12: gmt_blockmean_py — confirmed the predicted cheap win

Ported (`utils/gmt_blockmean_py.py`), wired at both `topo_interp_mode=1`
call sites in `dem2topo_ra`, gated by `GMTSAR_BLOCKMEAN_PY` (default OFF
pending a full sweep). Reused the `gmt_blockmedian_py` bin-partition
scaffold; mean reduction needs no per-bin sort, so it's simpler *and*
faster than blockmedian's own kernel — no Numba kernel needed, pure numpy
`reduceat`.

**Correction to the original prediction**: byte-identity is **not**
achievable (unlike blockmedian) — GMT's internal float64 summation order
isn't guaranteed to match numpy's, confirmed empirically. Uses the
project's documented doubles tolerance instead (`atol=1e-9`,
project_rules.md Rule 7 Phase C): real-data max abs diff 4.5e-12
(RS2_SLC_Hawaii) to 7.3e-12 (ALOS_haiti), and the **downstream
`topo_ra.grd` is byte-identical end-to-end** — the roundoff is fully
absorbed by the subsequent `surface`/`grdfill` fit, so this is a
non-issue in practice.

**Timing**: 19.3x faster at ALOS_haiti scale (906k rows, 2.28s→0.12s),
3.7x faster at RS2_SLC_Hawaii scale (965k rows, 0.29s→0.08s). Both gates
pass. Next step before flipping default ON: a full sweep across the
known-clean mode=1 PASS cases (see `bin_py/tests/test_gmt_blockmean_py.py`
docstring for the list) — 4 mode=1 cases have a pre-existing, unrelated
mode=0-vs-1 divergence not touched by this port.

## Never attempted, not worth it

| Command | Where | Why not |
|---|---|---|
| `gmt grdedit` | `utils/geocode` (10x), `utils/filter` (1x) | Pure header-metadata rewrite, ~ms each — no pixel compute to gain. |
| `gmt trend2d` | `utils/fitoffset.py:105,119-120` | Trivial 2D fit, <=6 coefficients, negligible wall-time. |
| `gmt grdlandmask` | `utils/landmask:58` | One-shot per case; needs the GSHHG coastline database — high effort for one call. |
| `psconvert`, `grdimage`, `makecpt`, `psscale`, `grdgradient`, etc. | figure-rendering call sites across `p2p_stages.py`, `snaphu.py`, `stack`, `grd2kml`, `grd2geotiff` | Final PNG/PDF output only — doesn't gate any numerical product. |
| ~60 other `gmt` subcommands (`grdinfo`, `grd2xyz`, `xyz2grd`, `gmtconvert`, `grdtrack`, `gmtinfo`, `project`, ...) | throughout `utils/` | Grid I/O / projection / metadata — see `docs/release_notes_v2.4.0.md` "Scope & dependencies" for the full accounting. GMT remains a hard runtime+build dependency; this is not a gap to close, it's the architecture. |

## Attempted 2026-07-12: SAR sensor preprocessors, tested empirically

The "deferred by design" judgment below was speculative until 2026-07-12,
when it was actually tested: parallel Mira ports of
`make_slc_s1a/csk/csk2/tsx/rs2/nsr` and `ALOS_pre_process`, each validated
for bit-parity against the real C binary on real cached test data (Rule 7),
each timed honestly. Preprocessing is **~7.8% of total case wall time**
(profiled sum across the 21-case sweep: `dem2topo_ra` 78.8%, `pre_proc`
7.8%, `merge_unwrap_geocode_tops` 5.6%, `geocode` 2.8%, `intf` 1.9%,
`resamp_py` 1.7%, `xcorr_py` 1.0%, `snaphu` 0.3%) — real but not where the
budget is, so a modest per-sensor slowdown is an acceptable tradeoff for
having a tested, bit-faithful Python alternative on record.

Results (parity always checked on real data, not synthetic — see
`bin_py/tests/test_make_slc_*_py.py` for each):

| Sensor | Parity | Speed vs C | Wired default |
|---|---|---|---|
| `make_slc_s1a` | PASS, byte-identical | **1.4-1.8x faster** (memmap bulk read replaces per-scanline TIFF calls) | `GMTSAR_S1A_PREPROC_PY`, OFF |
| `ALOS_pre_process` | PASS on the IMG-parsing subset only — LED/orbit/Doppler NOT ported (real ~2000-line transitive C closure, multi-day scope) | ~2.1x faster on the ported subset | not wired — parity is partial, no dispatcher created |
| `make_slc_rs2` | PASS, byte-identical | ~1.3x **slower** (I/O-bound, numpy overhead) | `GMTSAR_RS2_PREPROC_PY`, OFF |
| `make_slc_tsx` | PASS, byte-identical | ~on par to slower for one-shot calls (numpy import tax ~2.5-3s dominates) | `GMTSAR_TSX_PREPROC_PY`, OFF |
| `make_slc_nsr` | PASS, byte-identical (real 14GB NISAR_Ethiopia fixture, both freq modes) | **~19x faster** — h5py sliced reads (only the needed region) vs C mallocing the whole ~11GB array + per-pixel scalar cast loop | `GMTSAR_NSR_PREPROC_PY`, OFF pending review |
| `make_slc_csk2` | PASS, byte-identical (CSG-format fixture built via HDF5 hard-link onto real CSK_SLC_Italy pixel data — no real CSG product exists in the repo, disclosed in module/test docstrings) | ~4-5x **slower**, even after 2 optimization rounds (54s→21s) | dispatcher ready, no upstream caller wired (no CSG case exists yet) |
| `make_slc_csk` | PASS, byte-identical (3 real CSK_SLC_Italy SCS_B acquisitions incl. a 1.9GB SLC) | ~1.3-2x **slower** — I/O-bound HDF5 chunked reads dominate both sides | `GMTSAR_CSK_MAKE_SLC_PY`, OFF |

**All 7 planned preprocessor ports are now complete** (S1A, ALOS-partial,
RS2, TSX, NSR, CSK2, CSK). Final tally: 2 real wins (S1A 1.4-1.8x, NSR
19x), 1 partial-scope win (ALOS, LED/orbit not ported), 4 honest losses
(RS2, TSX, CSK2, CSK — all I/O-bound, all correctly wired OFF). Confirms
the empirical pattern: mechanical porting is genuinely easy, speed is a
coin flip on I/O-bound work, and every single port caught at least one
non-obvious verbatim-arithmetic or data-format trap that a synthetic-only
test would have missed (see the `str2double`/CSK1-vs-CSG/pop_led_hdf5
notes in each agent's own report, not repeated here).

Common non-obvious trap found in **every** port so far: each sensor's C
code parses XML/ASCII header fields with a hand-rolled digit-by-digit
`str2double` (not `strtod`/`float()`) — using Python's `float()` instead
silently diverges in the last ULP on real values. All ports above reproduce
`str2double`/`cat_nums`/date-parsing verbatim rather than substituting the
"obviously equivalent" library call. This is the real cost behind "easy to
port": the mechanical transcription is a few hours; catching this class of
trap is what actually takes the time.

**Verdict so far**: mixed, exactly as expected for I/O-bound code — S1A
wins, ALOS partially wins, RS2/TSX lose narrowly. None are wired on by
default pending review; all are honestly documented, tested alternatives.
Original speculative framing (below) is superseded by this table for the
4 sensors above — kept for the remaining un-tested ones.

- **SAR sensor preprocessors, remaining untested** (`make_slc_gf3/lt1`,
  `calc_dop_orb`, `extend_orbit`, `update_PRM`) —
  real, confirmed-unported C/Fortran source under `preproc/*/src*/`
  (233-407 lines each). `make_slc_gf3`/`lt1` excluded from the 2026-07-12
  round: no real regression-test tarball cached in `tests/cases.py`, so
  bit-parity validation per Rule 7a isn't possible yet. `ENVI_preproc` and
  `ERS_preproc` also excluded: ENVI vendors an entire third-party
  `epr_api-2.3` library, ERS has multiple format variants — both
  significantly more complex than the tested set, deferred to separate
  future scoping rather than assumed equally "easy."
- **`esarp.c` — scoped 2026-07-13, real range-Doppler SAR focuser, not a
  quick win.** The actual focusing math (range/azimuth compression) lives
  in `gmtsar/gmtsar/esarp.c` plus 10 linked files (~1150 total C lines:
  `rng_ref.c`, `rng_cmp.c`, `trans_col.c`, `rmpatch.c`, `acpatch.c`,
  `aastretch.c`, `shift.c`, `radopp.c`, `fft_bins.c`, `intp_coef.c`,
  `spline.c`), sharing ~30 PRM-derived globals via `soi.h` (no clean
  function signatures). Full findings:
  - **FFT**: GMT's own `GMT_FFT_1D()` API, runtime-dispatched inside
    libgmt — on this machine (`ldd bin/esarp`), that resolves to
    single-precision FFTW3 + threads. The exact backend is an external
    GMT-build detail, not fixed by this repo — any future port's "bit-
    faithful" oracle is only as stable as the linked GMT build; pin and
    document the GMT version before treating output as ground truth.
  - **Structure**: almost entirely per-line/per-column, not batched — one
    1-D FFT per range line (`rng_cmp.c`), one per range-bin column
    (`trans_col.c`), one forward+inverse pair per range bin in azimuth
    compression (`acpatch.c`). This is exactly a textbook batched-FFT
    vectorization case (`scipy.fft.fft(..., axis=..., workers=-1)`) —
    genuinely promising, 50-100x plausible, but batched vs. per-line FFTW3
    calls are different call sequences and parity must be proven
    empirically, not assumed.
  - **Algorithm**: a real range-Doppler focuser with range cell migration
    correction (`rmpatch.c`, 8-point sinc resampling — not
    `scipy.signal.resample`), range-varying azimuth matched filtering with
    a half-spectrum-split phase treatment (`acpatch.c`), and an optional
    azimuth stretch using a custom 1970-Goddard-algorithm cubic spline
    (`spline.c`) — explicitly NOT `scipy.interpolate.CubicSpline`'s
    boundary conditions. `spline.c`'s own header admits an *unexplained*
    Fortran-vs-C divergence at extrapolation boundaries, never resolved —
    a live known-quirk any port must get explicit sign-off on reproducing.
  - **Reference literature**: none in-tree (unlike `gmt_surface_py`, which
    had a citable Smith & Wessel 1990 paper). Sourced "from Howard Zebker
    ... Stanford interferometry package" (`esarp.c:7-8`) with ad hoc
    1996-2011 modifications layered on — correctness must be inferred by
    reading the C line-by-line, high risk of library-name-alike
    substitution (e.g. reaching for `scipy.signal.resample` where the C
    does something bespoke) on the RCMC and azimuth-compression stages.
  - **Test data**: already on disk, no new download needed —
    `work/csh_test/ALOS_Baja_EQ/raw/*.raw` + `.PRM` (esarp's exact input
    pair, 747MB), with a regenerable C oracle (`esarp` binary present,
    single CLI call, well under a minute to rerun fresh — existing `.SLC`
    outputs there are stale, per Rule 9, and must be regenerated, not
    reused as-is).
  - **Effort**: calibrated against today's 7-preprocessor-in-one-session
    baseline, this is NOT a one-session job — realistically **1-2 weeks**
    end-to-end (3-5x a preprocessor's effort), with RCMC and azimuth
    compression individually harder than any of the 7 preprocessors
    combined, and exactly the "vectorize a branch-dependent algorithm"
    trap Rule 7 warns about.
  - **Verdict**: still worth doing eventually — the batched-FFT case is
    real and test-data logistics are solved — but it needs to be staffed
    as a dedicated 1-2 week project with explicit sign-off on the
    `spline.c` extrapolation question and a pinned GMT/FFTW version for
    the oracle, not slotted in as "the next quick preprocessor-style
    port." The old "highest-leverage if focusing speed is ever
    prioritized" framing undersold both the difficulty and the specific
    two-checkpoint risk.

## Open questions carried over from PLAN.md (2026-07-13)

`PLAN.md` (the pre-2026-05-14 roadmap this file supersedes — see below)
had every Phase 1/2/4 utility it planned confirmed already shipped
(`baseline_table`, `make_dem`, `select_pairs`, `pre_proc_batch`,
`align_batch`, `intf_batch`, `batch_processing`, `unwrap_parallel`,
`prep_sbas`, `stack`, `stack_corr`, `stack_coherence_mask`,
`extract_one_time_series` all exist in `utils/`) — but 3 genuinely open
questions from its §8 never got answered and aren't tracked anywhere
else:

- **SBAS test fixture**: no multi-pair time-series tarball is in the
  regression sweep. `prep_sbas`/`stack`/`stack_corr` exist and presumably
  work, but have no case-level parity coverage against csh — unlike
  every single-pair P2P utility. Does `topex.ucsd.edu/gmtsar/tar/` host
  one, or does this need curating?
- **Parallelism budget**: should `*_parallel` utilities (`unwrap_parallel`,
  etc.) share the test sweep's `MAX_PARALLEL` env var, or manage their
  own? Unresolved — check for resource contention before running both
  concurrently on the same host.
- **csh deprecation horizon**: is the long-term goal to remove the
  remaining csh shell-out shims entirely, or keep them as an intentional
  fallback? Affects how aggressively future ports should touch internals
  vs. leave working shell-outs alone.

Also carried over: `docs/audits/AUDIT_stage_cache_mira57.md` documents
`tests/stage_cache.py` as "architecturally broken," needing a redesign
(fingerprint post-stage outputs instead of raw/mutate-restore) rather
than a bugfix — still `GMTSAR_STAGE_CACHE=0` by default, unclear if the
redesign was ever done. Worth a fresh look before trusting it.

`PLAN.md`'s full mission-log history (every dated status snapshot,
Mira-by-Mira roadmap, and the now-superseded `gmt_surface_py` perf
numbers — a *third*, independently stale figure for a story this file
already had to reconcile from two others) is archived unedited at
`docs/reports/PLAN_archived_2026-05-14_to_2026-06-13.md`. Its
still-relevant technical content (the GMT netCDF attribute spec) was
extracted to `docs/GMT_NETCDF_ATTR_SPEC.md`, which live code
(`utils/gmt_grd_io.py`, `utils_pygmt/gmt_compat.py`, `utils/gmt_inproc.py`)
now points to instead.

## How to keep this coherent

When any of the above changes, update this file **and** grep the talk
deck (`slides/20260722_python_framework_gui/slides.tex`) and any other
release notes that reference the same claim — this file exists because
three prior sources (two release notes, one session memory) disagreed
with each other and with the code on the surface-fitting story. Don't let
a fourth stale copy start the same problem again.
