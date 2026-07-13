# Release notes — v2.3.0 (2026-06-16)

## Full-Python surface by default

`GMTSAR_SURFACE_INPROC` now defaults to **ON**: the `dem2topo_ra` topo_ra step
uses the in-process Python solver `gmt_surface_py` (float32 GS-SOR, Smith &
Wessel biharmonic spline in tension) instead of shelling out to the `gmt
surface` C binary. This makes the surface/gridding compute core Python by
default, completing the compute-core port (xcorr, phasediff, conv, resamp,
SAT_*, blockmedian, phasefilt, and now surface all run in Python by default;
snaphu remains the C binary).

Set `GMTSAR_SURFACE_INPROC=0` to force the `gmt surface` C subprocess.

## Evidence

Full 21-case `GMTSAR_SURFACE_INPROC=1` sweep vs the csh oracle (preserved
reference): **20/21 py-vs-csh clean**. All Sentinel-1 TOPS cases
(Greece, LA, COVE), CSK_SLC_Italy, S1_Larsen_C, and every
ALOS/ALOS2/ENVI/ERS/TSX/NISAR/RS2/CSK_RAW family PASS.

## Known diff — S1_Ridgecrest_EQ H_res (documented, accepted)

The lone non-clean case is `S1_Ridgecrest_EQ`: its H_res raw `phasefilt.grd`
shows complex-rms 0.352 (threshold 0.15), confined **entirely** to the
unconstrained **no-DEM corner** (scatter data ends at y=11160 but the grid
extends to y=12192). There the topographic-phase correction is undefined for
*both* C and Python (each extrapolates the unconstrained biharmonic surface
differently; the GS-SOR does not converge that region within `-N1000` for
either implementation). These are high-coherence pixels with no DEM signal —
the difference is scientifically meaningless, and S1_Ridgecrest's **masked and
merged** products match C. `gmt_surface_py` matches `gmt surface` to ~0.00m
everywhere data exists (e.g. CSK interior RMS 0.0666m).

This corrects the earlier "convergence-floor / high-relief" framing (Mira #72),
which was wrong — the divergence is specifically the no-DEM zone, not relief.

## Also in this release

- `test_gmt_surface_py.py`: fixed a `_time`→`time` typo that had been crashing
  the gated CSK real-scale parity test (landed in v2.1.42).

## Performance note

The pure-Python/Numba surface is ~1.14× the wall-time of C `gmt surface`
(iteration counts already match C to 1–2%; the residual is Numba-LLVM vs gcc
per-node throughput). A Cython kernel for the GS-SOR inner loop to reach ≤1.0×
is in progress (tracked separately).
