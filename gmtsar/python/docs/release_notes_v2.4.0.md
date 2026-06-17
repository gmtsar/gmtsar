# Release notes — v2.4.0 (2026-06-17)

## Milestone: every compute core runs in Python by default, verified vs csh

v2.4.0 marks the completion of the compute-core port. With all in-process
Python defaults enabled, a full 21-case sweep against the csh oracle is
**20/21 py-vs-csh clean** — the lone diff being the long-documented
`S1_Ridgecrest_EQ` no-DEM-corner surface artifact (phasefilt complex-rms
0.3516, undefined for both C and Python where the DEM does not cover the
H_res grid; masked/merged products match).

### Compute cores now Python-by-default

| Core | Python module | Default |
|------|---------------|---------|
| Cross-correlation | `xcorr_py` | ON |
| Phase difference | `phasediff_py` | ON |
| Convolution | `conv` (Python) | ON |
| Resampling | `resamp_py` | ON |
| SAT_llt2rat / SAT_look trio | `utils/vector.py` | ON |
| Block median | `gmt_blockmedian_py` | ON |
| Phase filter | `phasefilt_py` | ON |
| Surface (biharmonic spline) | `gmt_surface_py` (+ Cython GS-SOR kernel) | ON (v2.3.0) |
| grdmath operators | `gmt_grdmath_py` | ON (v2.3.8) |
| grdsample | `gmt_grdsample_py` | ON |
| grdfilter / grdfill | `gmt_grdfilter_py` / `gmt_grdfill_py` | available |

### snaphu (phase unwrapping)

snaphu remains the **C binary in production**. The pure-Python/numba port
(`bin_py/snaphu_py/`) is a verified **correctness/audit reference**: the
network-simplex anti-cycling bug was solved in v2.3.7 (30×30 and 64×64 real
ALOS_haiti patches are float32-exact vs the C binary). A Cython kernel
(v2.3.9, experimental, unwired) confirmed the remaining gap is a
**struct-of-arrays vs array-of-structs cache-layout** constant factor
(~125×), not algorithm or interpreter — so full-grid production speed would
require an AoS rewrite or a cffi→C wrap. Since snaphu is ~0.3% of pipeline
wall-time (macro profile), production stays on the C binary.

## What got here (v2.3.6 → v2.4.0)

- **v2.3.6** — fixed `grdmath_corr_chain` GMT native `=bf` header (wrong
  registration/offsets) so `conv` reads `corr.grd` at the correct dims.
- **v2.3.7** — solved the snaphu network-simplex anti-cycling remount bug
  (matched C's `snaphu_solver.c` thread-rewire + WrapPhase seed).
- **v2.3.8** — flipped `GMTSAR_GRDMATH_PY` default OFF→ON (20/21 sweep).
- **v2.3.9** — experimental Cython snaphu kernel + SoA-cache diagnosis.
- **v2.4.0** — full all-Python-defaults 21-case capstone sweep, 20/21 clean.

## Performance note (the next chapter)

A macro profile across the matrix shows `dem2topo_ra` / **surface dominates
end-to-end wall-time (36–81% per case)**; snaphu is ~0.3%. Surface is
already at ~1.0–1.14× the `gmt surface` C binary (Cython kernel), so further
speedup requires an algorithmic change (multigrid, red-black SOR) or GPU —
each of which alters update order and therefore **breaks bit-identity** with
`gmt surface`. That parity-vs-speed tradeoff is the central decision for the
optimization phase.
