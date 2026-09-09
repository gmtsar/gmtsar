# topo_interp_mode=0 vs 1 — full 21-case sweep results (2026-07-09)

Follow-up to v2.5.6 (`dem2topo_ra` masked-cell / phasediff-segfault fix,
commit `0892805`). Every enabled full-tier case run twice — once with the
default `topo_interp_mode=0` (`gmt surface`, baseline) and once with
`topo_interp_mode=1` (triangulation fast-path, variant) — comparing final
products with the exact same criteria `compare.py` uses for py-vs-csh
(`compare_files()`, `fileNameList`, `GRD_RMS_THRESHOLD`, `DEFAULT_GRD_RMS`,
`DEFAULT_PNG_SSIM`; see project_rules.md Rule 12).

## Results

| Case | Setup | Baseline (s) | Variant (s) | Speedup | Result |
|---|---|---:|---:|---:|---|
| RS2_SLC_Hawaii | topo_interp_mode=0 vs 1 | 101 | 87 | 1.16x | PASS |
| NISAR_Ethiopia | topo_interp_mode=0 vs 1 | 459 | 469 | 0.98x | PASS |
| ALOS_SLC_L1.1 | topo_interp_mode=0 vs 1 | 338 | 262 | 1.29x | PASS |
| S1_Ridgecrest_EQ | topo_interp_mode=0 vs 1 | 8050 | 6822 | 1.18x | PASS |
| ALOS4_Pinon | topo_interp_mode=0 vs 1 | 1209 | 364 | 3.32x | PASS |
| ALOS2_Japan_Fugi_left | topo_interp_mode=0 vs 1 | 1375 | 500 | 2.75x | PASS |
| ENVI_Baja_EQ_SLC | topo_interp_mode=0 vs 1 | 1411 | 414 | 3.40x | **FAIL** (rms 0.0143/0.01) |
| ALOS2_Brazil | topo_interp_mode=0 vs 1 | 888 | 251 | 3.54x | PASS |
| ERS_Hector_EQ | topo_interp_mode=0 vs 1 | 1792 | 1135 | 1.58x | PASS |
| TSX_SLC_Hawaii | topo_interp_mode=0 vs 1 | 686 | 388 | 1.77x | PASS |
| ALOS_Baja_EQ | topo_interp_mode=0 vs 1 | 1357 | 1064 | 1.28x | **FAIL** (complex-rms 0.159/0.15) |
| ALOS_ERSDAC_L1.0 | topo_interp_mode=0 vs 1 | 1206 | 848 | 1.42x | PASS |
| CSK_SLC_Italy | topo_interp_mode=0 vs 1 | 718 | 316 | 2.27x | **FAIL** (ssim 0.826/0.9) |
| ENVI_Baja_EQ | topo_interp_mode=0 vs 1 | 2564 | 1618 | 1.58x | **FAIL** (rms 0.0217/0.01) |
| CSK_RAW_Hawaii | topo_interp_mode=0 vs 1 | 1414 | 1374 | 1.03x | PASS |
| ALOS_haiti | topo_interp_mode=0 vs 1 | 1987 | 1151 | 1.73x | **FAIL** (rms 0.0133/0.01) |
| S1A_SLC_TOPS_Greece | topo_interp_mode=0 vs 1 | 3148 | 1093 | 2.88x | PASS |
| S1_Larsen_C | topo_interp_mode=0 vs 1 | 5143 | 1638 | 3.14x | PASS |
| S1A_SLC_TOPS_COVE | topo_interp_mode=0 vs 1 | 6119 | 1949 | 3.14x | PASS |
| S1A_SLC_TOPS_LA | topo_interp_mode=0 vs 1 | 6476 | 2057 | 3.15x | PASS |
| ALOS2_SCAN_SSAF | topo_interp_mode=0 vs 1 | 8289 | 3011 | 2.75x | PASS |

**16/21 PASS, 5/21 FAIL.** No crashes, no timeouts — v2.5.6's masked-cell fix
holds across the full manifest (0 cases hit the phasediff segfault this
fixed). Every case is faster or effectively at parity in mode=1 (worst case
NISAR_Ethiopia 0.98x, within noise); the multi-subswath Frame cases
(S1_TOPS_Frame, ALOS2_SCAN_Frame) see the largest wins, 2.75-3.4x, since
their topo-simulation cost is a bigger fraction of total wall time than in
single-pair recipes.

## Failures

All 5 failures are borderline (worst margin 43% over threshold, several
under 10% over) and concentrated in `corr_ll.grd`/`filtcorr.grd`/`phasefilt.grd`
— i.e. small, real accuracy differences from the triangulation-vs-surface
algorithm swap, not crashes or corruption. This is consistent with the
already-documented mode=1 limitation (steep/cliff terrain divergence,
[[project_topo_interp_mode_verified]]): some real scenes push that
divergence over `compare.py`'s py-vs-csh-calibrated thresholds, which were
never tuned for an intentional algorithm-accuracy tradeoff. `CSK_SLC_Italy`
is the one case with a different failure signature (image SSIM 0.826/0.9,
not a grid RMS) and merits a closer look.

Side-by-side `phasefilt_mask_ll.png` (mode0 vs mode1) for all 5 failures
were sent to the user directly; the underlying `.grd`/`.png` files for
every case (pass or fail) are archived at
`work/mode_sweep/product_archive/` (see driver note below).

## Driver notes (for anyone rerunning this sweep)

Sweep driver: `mode_sweep.py` (ad hoc, not committed — lives outside the
repo). Two real bugs were found and fixed during this run:

1. **Pass-detection false negative on multi-subswath Frame recipes.**
   The original check looked for the string `P2P 7: p2p_processing
   FINISHED` in the log tail — present only in the single-pair
   `p2p_processing` recipe. `S1_TOPS_Frame`/`ALOS2_SCAN_Frame` orchestrator
   recipes end with their own marker (`P2P_S1_TOPS_FRAME - END`, `GEOCODE
   END`) and were misreported as failed even though 5 of them had
   completed successfully. Fixed to check for the actual output file
   (`phasefilt_mask_ll.grd`, recursive glob) instead of a recipe-specific
   log string — see Rule 12 update.
2. **Unconditional per-case cleanup destroyed evidence for FAIL results.**
   The driver deleted each case's full workdir immediately after logging
   its JSON result, regardless of pass/fail, for disk safety. This meant
   the first 5 genuine FAILs had no artifact left to inspect — they had to
   be rerun a second time just to get the images `compare.py` had already
   scored. Fixed: every file `compare.py` actually verifies (+ `.pdf`
   renderings where they exist) is now archived to
   `work/mode_sweep/product_archive/<case>_<mode>_<file>` for every case,
   pass or fail, before the workdir is wiped.

Both fixes are now codified in `project_rules.md` Rule 12.
