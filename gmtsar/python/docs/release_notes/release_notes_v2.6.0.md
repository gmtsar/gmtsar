# v2.6.0 — full-sweep confirmation of 5 preprocessor + blockmean flips, write_gmt_grd symlink fix, logging hardening

## Full 21-case sweep: promotes v2.5.7's "winners, pending a full sweep" to confirmed

`make_slc_s1a_py` (`GMTSAR_S1A_PREPROC_PY`), `make_slc_nsr_py`
(`GMTSAR_NSR_PREPROC_PY`), and `gmt_blockmean_py` (`GMTSAR_BLOCKMEAN_PY`)
were flipped default ON in v2.5.7 on isolated real-data parity+timing
tests only. This release runs the full 21-case sweep those flips were
gated on. Also flipped this session, same gate: `GMTSAR_RS2_PREPROC_PY`
and `GMTSAR_TSX_PREPROC_PY` (deployment-simplicity rationale — see
project_rules.md Rule 13a: uniformly-ON preprocessor defaults simplify
install/deploy even where an individual module is measurably slower).

**Result: 156/161 comparisons pass across all 21 cases** (post-fix
state, after `ALOS_haiti`'s re-validation below; the sweep as originally
launched — before the write_gmt_grd fix landed mid-sweep — was 155/161).
The 5 remaining failures are the one known, non-regression case, not a
new bug:

- `S1_Ridgecrest_EQ` (5 failures, all `H_res/intf/2019184_2019196`):
  the documented no-DEM corner (phasefilt complex-rms 0.3516, matching
  the "~0.35" figure on record since 2026-06-14). The only accepted
  in-sweep failure per project_rules.md Rule 10.
- `ALOS_haiti` (1 failure, `phasefilt_mask_ll.png`): caught by this same
  sweep mid-fix (see below) — re-validated separately after the fix
  landed and now passes 7/7.

Full per-case pass/fail, perf, and per-binary cost breakdown:
`docs/perf_snapshots/perf_snapshot_2026-07-13T10-26-01Z_566566e_full.md`.
Fresh byte-level baseline blessed for all 21 cases at
`docs/blessed_scorecards/v2.6.0/` (previous latest blessed tag was
v2.3.0, several releases stale).

## Fixed: write_gmt_grd broke GMT's symlink-follow-and-mutate semantics

Root cause of the `ALOS_haiti` failure above. `gmt_grd_io.py`'s
`write_gmt_grd()` called `os.remove(grd_path)` before writing — when
`grd_path` is a symlink (as `snaphu.csh`'s `phase_patch.grd ->
phasefilt.grd` landmask-masking alias creates, mirrored in `snaphu.py`),
this deletes only the symlink instead of following it and mutating the
target in place, which is what GMT's own C netCDF writer does. Silently
broke `phasefilt.grd`'s NaN footprint (py 1.9% NaN vs. csh 40.3% NaN on
this case), which propagated three stages downstream into
`proj_ra2ll`'s data-driven `-R` region computation as a pixel-dimension
mismatch (py 2190x2180 vs. csh 2090x2150). Introduced 2026-06-18,
unrelated to any change in this release; found by this sweep, fixed by
resolving the symlink before write. New regression tests added in
`bin_py/tests/test_gmt_grd_io.py::TestSymlinkAliasedWrite` (one runs the
real `gmt grdmath` C binary as ground truth). Commit `566566e`.

## Logging hardening: every case log is now self-sufficient for backtracking

Prompted by a real gap found this session: confirming whether
`GMTSAR_SURFACE_INPROC` actually ran in-process for a given sweep
required inferring it from a side-effect (counting `gmt surface`
subprocess lines in `log.txt`) rather than reading it directly.

- `p2p_processing` now prints a timestamped header at the start of every
  run: every `GMTSAR_*_PY`/`*_INPROC` env gate's effective value (with a
  `*` marker when using the code default, not an explicit override),
  thread/concurrency knobs (`OMP_NUM_THREADS` etc. — Rule 12c: perf
  numbers from an oversubscribed run aren't trustworthy), the resolved
  git sha, and argv.
- `gmtsar_lib.run()` now logs a UTC timestamp, elapsed time, and exit
  code for every subprocess call unconditionally (previously only under
  `GMTSAR_PROFILE=1`).

Net effect: `work/python_test/<case>/log.txt` is now sufficient on its
own to answer "what backend ran, with what config, when, and how long
did each step take" — no more log archaeology.

## Fixed: a real test-quality bug in test_phasefilt.py

`TestCParityCSK`/`TestCParityALOS`'s `max_diff`/`rms_diff` computed a
raw (non-wrap-invariant) subtraction on wrapped phase values. A pixel
landing on opposite sides of the +-pi branch cut (py=+pi, C=-pi — the
same angle) reported a spurious ~2*pi outlier, which is exactly the
failure mode this project's own established phase-comparison convention
(wrap-invariant complex-RMS, `tests/compare.py`) exists to avoid — this
unit test simply predated that convention. Fixed with
`np.angle(exp(1j*diff))`. Unmasked a real, tiny, previously-hidden
worst-case pixel (float32 FFTW roundoff on a low-amplitude pixel,
7.558e-3 rad, reproducible) — widened `MAX_ABS_DIFF` 7e-3 -> 8e-3 with
the investigation documented inline; `rms_diff`/`complex_rms` were
already ~1e-5, far inside tolerance throughout. 25/25 tests pass.

## Fixed: dem2topo_ra topo_interp_mode=1 crashed at the default gate

Found by the same full-suite run: `_triangulate_dispatch()`'s `gmt
triangulate` subprocess fallback branch (the DEFAULT branch, since
`GMTSAR_TRIANGULATE_PY=0` by default) referenced a free variable `V`
that was never in its scope — a `NameError` on every single
`topo_interp_mode=1` run with the default gate. `topo_interp_mode=1` is
opt-in per-case (default is `mode=0`), which is why this had gone
unnoticed. Fixed by passing the caller's resolved `-V`/`''` verbosity
flag explicitly (`v_flag` parameter) instead of relying on the enclosing
function's local. `bin_py/tests/test_dem2topo_ra.py::
TestMode1ArgRegression::test_mode1_produces_topo_ra_grd` now passes.

## Known, documented, non-blocking: proj_ra2ll_fast NaN-mask boundary drift

The same full-suite run also surfaced `test_proj_ra2ll_fast.py::
TestProjRa2llFastVsSubprocess::test_all_files_bit_exact` failing — a
real but negligible pre-existing issue (since at least v2.5.4, unrelated
to this release): ~8 pixels out of 1.29M (0.0006%) have their NaN-mask
boundary shifted by one column between `proj_ra2ll_fast` (the in-process
path `geocode` actually uses in production) and a fresh `proj_ra2ll`
subprocess call. Same class of issue as the already-documented
proj_ra2ll region-rounding divergence. Explains why the real 21-case
sweep — which exercises this exact code path — still passes SSIM/RMS
cleanly: the magnitude is far below any `compare.py` threshold. Not
fixed this release (unrelated in scope, no impact on any real pass/fail
outcome); tracked in `docs/PATHWAY_FORWARD.md`'s Known-bug section.

## README: added a Performance section

`gmtsar/python/README.md` previously had no perf numbers at all — just
install/test instructions. Added a table (ranked by speedup, aggregate
1.06x wall-time-weighted) and a real side-by-side visual
(`docs/perf_example_nisar.png`, `NISAR_Ethiopia`, generated from actual
sweep output via `tools/py_vs_csh_figure.py`), anchored to this release.

## Also this release

- `.gitignore`: `gmt.history` (GMT's per-directory session-state file,
  was leaking into `git status` noise).

## Test evidence

Full 21-case sweep: 156/161 pass post-fix (see above). `bin_py/tests/` full
suite: 570/571 executed pass, 17 skipped (the 1 remaining failure is the
documented, non-blocking `proj_ra2ll_fast` boundary drift above — not a
regression). `ALOS_haiti` re-validated standalone post-fix: 7/7.

Commits: `d4c3807` (blockmean flip), `566566e` (write_gmt_grd fix),
`fe953d2` (logging hardening + phasefilt test fix + v2.6.0 blessing).
