# Release notes — v2.2.0 (Python compute-core milestone)

**Date:** 2026-06-13
**Tag:** v2.2.0
**Baseline:** v2.0.x Python framework + the v2.1.x port series

## Summary

v2.2.0 marks the point where the **heavy numerical compute cores of the GMTSAR
InSAR pipeline run as in-process Python by default**, validated bit-faithful to
the original C binaries on real data across the full 21-case regression suite —
and **faster than the csh/C pipeline in aggregate**.

- **Accurate:** 21/21 cases py-vs-csh CLEAN (all scorecard metrics under
  threshold) on a full `SWEEP_FORCE` sweep, same host.
- **Faster:** aggregate **0.88×** of the csh pipeline wall-time (20 cases faster,
  1 at parity, 0 slower).

## Compute cores ported to Python (default ON, validated)

`xcorr`, `phasediff`, `conv`, `resamp`, `SAT_llt2rat`, `SAT_baseline`,
`make_los`, `blockmedian` — plus the GMT helper ops `grdcut`, `grdfill`,
`grdsample`, `xyz2grd`, `m2s`. Each carries a C-parity-on-real-data test in
`bin_py/tests/`.

## Still on the C binary (not yet Python)

- **`gmt surface`** — the topo_ra interpolation in `dem2topo_ra`. A Python port
  (`gmt_surface_py`) exists and is bit-faithful on smooth synthetic grids, but
  its GS-SOR solver diverges from `gmt surface` on real heterogeneous terrain
  (~0.46 m RMS, the "Mira #72" limitation). It is retained behind
  `GMTSAR_SURFACE_INPROC=1` for testing; the default is OFF (C subprocess) until
  the solver-accuracy gap is closed. (Fix in progress.)
- **`phasefilt`** (Goldstein/Baran adaptive filter) — a validated Python port
  (`bin_py/phasefilt_py`, complex-RMS 8.6e-6 vs C) is staged behind
  `GMTSAR_PHASEFILT_PY=1`, default OFF pending end-to-end sweep validation.
- **`snaphu`** — phase unwrapping remains the external C binary. A Python port is
  scoped (I/O layer complete; network-flow solver is a multi-week effort).

## Bugs fixed in the v2.1.31–35 series

- **v2.1.31** `gmt_surface_py`: pixel-registration + gcd-expansion parity with C
  `surface` (rms 1.2e-7).
- **v2.1.32** flipped `GMTSAR_SURFACE_INPROC` ON — later found premature (see
  v2.1.35).
- **v2.1.33** `dem2topo_ra._surface_inproc`: corrected `omega` 0.5→1.4 (C's
  `SURFACE_OVERRELAXATION`) and `max_iter` 2000→1000 (C's `-N1000`). The wrong
  under-relaxation had both crawled and diverged on large grids.
- **v2.1.34** `xcorr_py`: replicated C's two `md`-buffer side effects — the
  stale-allocation (never re-zeroed across calls) and the **in-place forward-FFT**
  side effect of `fft_interpolate_2d`. The latter was the dominant cause of a
  3.3 px sub-pixel divergence on high-SNR rows that propagated through
  `fitoffset`→`resamp`→`phasefilt`/`los`. Fixed ALOS_haiti.
- **v2.1.35** reverted `GMTSAR_SURFACE_INPROC` to default OFF: `gmt_surface_py`'s
  solver isn't accurate enough on real terrain (Mira #72), which had broken CSK
  and S1_Ridgecrest and driven a 1.33× perf regression. Reverting to the C
  surface subprocess restored both correctness (byte-identical topo_ra) and
  performance.

## Performance — py vs csh (full 21-case sweep, same host, AMD EPYC 7F72)

py = this release (surface on C subprocess, cores in Python); csh = stock
C/csh pipeline. Lower py/csh is faster.

| case | py (s) | csh (s) | py/csh |
|------|-------:|--------:|-------:|
| RS2_SLC_Hawaii | 86 | 182 | 0.47 |
| NISAR_Ethiopia | 286 | 454 | 0.63 |
| ALOS_SLC_L1.1 | 293 | 431 | 0.68 |
| TSX_SLC_Hawaii | 622 | 782 | 0.80 |
| ALOS2_SCAN_SSAF | 7350 | 8961 | 0.82 |
| CSK_SLC_Italy | 658 | 791 | 0.83 |
| ALOS_ERSDAC_L1.0 | 760 | 904 | 0.84 |
| CSK_RAW_Hawaii | 607 | 726 | 0.84 |
| S1_Ridgecrest_EQ | 7789 | 9244 | 0.84 |
| ALOS_Baja_EQ | 912 | 1046 | 0.87 |
| ALOS2_Japan_Fugi_left | 1200 | 1383 | 0.87 |
| ALOS2_Brazil | 833 | 944 | 0.88 |
| ALOS4_Pinon | 1072 | 1209 | 0.89 |
| ENVI_Baja_EQ | 1541 | 1735 | 0.89 |
| ENVI_Baja_EQ_SLC | 1276 | 1427 | 0.89 |
| ERS_Hector_EQ | 1096 | 1212 | 0.90 |
| ALOS_haiti | 1563 | 1713 | 0.91 |
| S1A_SLC_TOPS_LA | 6200 | 6677 | 0.93 |
| S1A_SLC_TOPS_COVE | 5096 | 5497 | 0.93 |
| S1A_SLC_TOPS_Greece | 2850 | 2998 | 0.95 |
| S1_Larsen_C | 4888 | 4965 | 0.98 |
| **TOTAL** | **46978** | **53281** | **0.88** |

20 faster, 1 at parity, 0 slower. Full machine/env snapshot:
`docs/perf_snapshots/perf_snapshot_2026-06-14T00-22-55Z_01429c6_full.md`.

## Correctness

21/21 py-vs-csh CLEAN. Blessed scorecards: `docs/blessed_scorecards/v2.2.0/`.
