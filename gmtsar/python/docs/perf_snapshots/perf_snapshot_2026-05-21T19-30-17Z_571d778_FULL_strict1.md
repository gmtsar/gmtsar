# Perf snapshot — strict-single-thread FULL sweep, 2026-05-21T19-30-17Z

**Commit:** `571d778` (master)  
**Config:** `NUMBA_NUM_THREADS=1 XCORR_PY_WORKERS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 MAX_PARALLEL=12 SWEEP_FORCE=py`  
**Hardware:** 48-core Intel Xeon, 1 TB RAM, NFS work dir (theo2)  
**Software:** GMT 6.5.0, Python 3.12, Numba 0.59.1  
**Sweep wall:** 11:36 → 14:29 = 2h 53m  
**xcorr_py fix (2fea441) was NOT yet applied** at the time NISAR ran in this sweep. NISAR result expected to be 6/0 after fix verification.

**Coverage:** 20/20 cases. **18 pass / 2 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 175s | 105s | +70s | 1.67× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 911s | 907s | +4s | 1.00× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 422s | +1s | 1.00× | 6/0 |
| ✓ ENVI_Baja_EQ | 1740s | 1742s | -2s | 1.00× | 6/0 |
| ✗ ALOS_haiti | 1749s | 1755s | -6s | 1.00× | 6/1 |
| ✓ ERS_Hector_EQ | 1244s | 1251s | -7s | 0.99× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1427s | -20s | 0.99× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6690s | 6876s | -186s | 0.97× | 10/0 |
| ✓ ALOS2_Brazil | 935s | 961s | -26s | 0.97× | 6/0 |
| ✓ ALOS_Baja_EQ | 1076s | 1106s | -30s | 0.97× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1268s | -38s | 0.97× | 6/0 |
| ✓ S1A_SLC_TOPS_COVE | 5507s | 5705s | -198s | 0.97× | 10/0 |
| ✓ S1_Larsen_C | 4944s | 5125s | -181s | 0.96× | 10/0 |
| ✓ ALOS2_SCAN_SSAF | 8921s | 9791s | -870s | 0.91× | 14/0 |
| ✓ S1A_SLC_TOPS_Greece | 3007s | 3327s | -320s | 0.90× | 10/0 |
| ✗ NISAR_Ethiopia | 432s | 480s | -48s | 0.90× | 2/4 |
| ✓ ALOS2_Japan_Fugi_left | 1346s | 1625s | -279s | 0.83× | 6/0 |
| ✓ CSK_SLC_Italy | 803s | 1000s | -197s | 0.80× | 6/0 |
| ✓ CSK_RAW_Hawaii | 703s | 961s | -258s | 0.73× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 1021s | -282s | 0.72× | 6/0 |

## Table 2 — Per-binary timing (single-pair cases only)

S1 TOPS cases + ALOS2_SCAN_SSAF use csh recipes — no per-binary profile (see PLAN section 7b).

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|----------:|---------:|--------:|-----:|---------:|
| ALOS_haiti | **1729s** | 846s | 201s | 30s | 69s | 52s | 15s |
| ENVI_Baja_EQ | **1709s** | 975s | 198s | 28s | 171s | 29s | 7s |
| ALOS2_Japan_Fugi_left | **1549s** | 844s | 432s | 27s | 53s | 46s | 44s |
| ENVI_Baja_EQ_SLC | **1398s** | 1058s | 101s | 28s | 110s | 17s | 22s |
| ERS_Hector_EQ | **1227s** | 751s | 111s | 27s | 122s | 15s | 3s |
| ALOS4_Pinon | **1200s** | 828s | 152s | 28s | 71s | 21s | 13s |
| ALOS_Baja_EQ | **1087s** | 331s | 201s | 28s | 77s | 54s | 40s |
| TSX_SLC_Hawaii | **968s** | 327s | 424s | 30s | 54s | 43s | 21s |
| CSK_SLC_Italy | **964s** | 400s | 386s | 27s | 37s | 41s | 21s |
| CSK_RAW_Hawaii | **939s** | 88s | 401s | 46s | 25s | 46s | 15s |
| ALOS2_Brazil | **926s** | 647s | 139s | 27s | 34s | 20s | 12s |
| ALOS_ERSDAC_L1.0 | **879s** | 413s | 102s | 28s | 100s | 14s | 14s |
| ALOS_SLC_L1.1 | **401s** | 110s | 111s | 36s | 49s | 14s | 20s |
| NISAR_Ethiopia | **294s** | 25s | 22s | 39s | 44s | 3s | - |
| RS2_SLC_Hawaii | **95s** | 36s | 11s | 27s | 13s | 2s | 1s |

## Table 3 — Aggregate cost by stage (across 15 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 7678s | 50.0% | gmt-wrapper |
| resamp_py | 2992s | 19.5% | Numba py |
| geocode | 1028s | 6.7% | gmt-subprocess |
| xcorr_py | 456s | 3.0% | scipy.fft py |
| intf | 417s | 2.7% | C bin |
| pre_proc | 248s | 1.6% | C bin |
| snaphu | 134s | 0.9% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not 6/0)

### ALOS_haiti — score 6/1, py=1755s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| los_ll.grd | ✗ FAIL | — |

### NISAR_Ethiopia — score 2/4, py=480s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✗ FAIL | — |
| filtcorr.grd | ✗ FAIL | — |

---

_Snapshot generated: 2026-05-21T19-30-17Z_  
_Source: sweep_strict_20260521_113631.log_
