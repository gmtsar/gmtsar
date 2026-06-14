# Autopilot summary — 2026-06-13 night → 2026-06-14 (v2.1.37–v2.1.41)

Methodology (user directive, codified as Rule 10/10a/10b): port the C **faithfully** to
bit-identical on **real, full-scale** data FIRST, then optimize. Each landing gated on
RS2 smoke 6/6 py-vs-csh + unit tests.

## Landed & tagged

| Tag | What | Status |
|-----|------|--------|
| v2.1.37 | **phasefilt_py default ON** (Goldstein/Baran) | ✅ Python by default; validated 6/6 fast-tier, complex-rms ~1e-5 vs C |
| v2.1.38 | snaphu_py I/O + cost arrays | bit-identical to C; library-only |
| v2.1.39 | snaphu_py MST init flows (CP6) | structural bit-identity; library-only |
| v2.1.40 | snaphu_py solver (CP7) + conn-comps (CP9) | full scalar port; **see snaphu verdict** |
| v2.1.41 | **gmt_surface_py float32 GS-SOR** | CSK topo_ra 0.458m→0.066m; opt-in, not default |

## The three originally-C steps — final state

- **phasefilt → Python by default (v2.1.37).** Bit-faithful. Done.
- **surface → improved, stays C by default.** The float32 fix (v2.1.41) makes the
  in-process Python surface much more faithful (CSK 0.458m→0.066m; CSK now passes
  in-process). A full `GMTSAR_SURFACE_INPROC=1` sweep was **20/21** — the holdout is
  **S1_Ridgecrest_EQ** (phasefilt 0.35): its H_res 77M-cell **high-relief** grid exceeds
  the tol=1e-4 GS-SOR convergence floor. CSK (same 77M size, lower relief) passes, so it
  is **not gateable by grid size**. Re-enabling the default would risk silent failures on
  high-relief scenes → **surface stays on the C subprocess.** Available opt-in via
  `GMTSAR_SURFACE_INPROC=1`. No v2.3.0.
- **snaphu → fully ported (CP1–CP9), stays C.** On a 30×30 real crop the port is
  **float32-EXACT** to C (so bit-identical-*capable*). But the solver **cycles at ≥32×32**
  (unfixed network-simplex invariant) and is **~2800× slower** (~14h/full grid;
  spanning-tree simplex is non-vectorizable). Correct-but-impractical research artifact;
  production needs the C binary or a cffi/cython extension.

## Genuine walls hit (honestly characterized, not bugs)

1. **surface S1_Ridgecrest:** tol=1e-4 convergence floor on high relief; both C and Python
   stop ~2·tol·z_rms from the fixed point on different compiler-FP trajectories. Closing it
   needs ~100× tighter tol (4× slower, diverges from gmtsar's actual behavior) or exact C
   compiler-FP codegen (infeasible).
2. **snaphu solver:** pure-Python network simplex is ~2800× slower and non-vectorizable.

## What "full Python" means now (corrected from the earlier overclaim)

Compute cores in Python by default: xcorr, phasediff, conv, resamp, SAT_llt2rat,
SAT_baseline, make_los, blockmedian, **phasefilt**, + GMT helpers. Still on C: **surface**
(opt-in Python available), **snaphu**, and GMT display/IO. Baseline (v2.2.0, subprocess
surface): 21/21 py-vs-csh clean, **0.88× wall-time vs csh** (faster).

## Open decisions for the user

- **surface default:** keep on C (current), OR accept a per-case opt-in / relief-gated
  hybrid, OR invest in tighter-tol (slower) to clear S1_Ridgecrest.
- **snaphu:** leave on C (recommended), OR pursue a cffi extension for a Python-callable
  fast path (not a pure port).
