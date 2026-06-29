# Perf snapshot — full, 2026-06-18T05-21-13Z

**Commit:** `c4b4fa5` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 2h 58m (10714s)  

**Coverage:** 21 cases with scorecards. **0 pass / 21 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✗ S1_Ridgecrest_EQ | 9107s | 3013s | +6094s | 3.02× | 0/16 |
| ✗ NISAR_Ethiopia | 454s | 176s | +278s | 2.58× | 0/6 |
| ✗ RS2_SLC_Hawaii | 182s | 72s | +110s | 2.53× | 0/6 |
| ✗ ALOS_SLC_L1.1 | 431s | 213s | +218s | 2.02× | 0/6 |
| ✗ TSX_SLC_Hawaii | 782s | 531s | +251s | 1.47× | 0/6 |
| ✗ ALOS_ERSDAC_L1.0 | 904s | 650s | +254s | 1.39× | 0/6 |
| ✗ CSK_RAW_Hawaii | 726s | 526s | +200s | 1.38× | 0/6 |
| ✗ ENVI_Baja_EQ | 1735s | 1288s | +447s | 1.35× | 0/6 |
| ✗ CSK_SLC_Italy | 791s | 600s | +191s | 1.32× | 0/6 |
| ✗ ALOS_haiti | 1713s | 1313s | +400s | 1.30× | 0/6 |
| ✗ ALOS_Baja_EQ | 1046s | 826s | +220s | 1.27× | 0/6 |
| ✗ S1A_SLC_TOPS_LA | 6667s | 5334s | +1333s | 1.25× | 0/10 |
| ✗ ALOS2_Japan_Fugi_left | 1383s | 1115s | +268s | 1.24× | 0/6 |
| ✗ S1A_SLC_TOPS_Greece | 3010s | 2432s | +578s | 1.24× | 0/10 |
| ✗ ALOS2_Brazil | 944s | 775s | +169s | 1.22× | 0/6 |
| ✗ ALOS4_Pinon | 1209s | 997s | +212s | 1.21× | 0/6 |
| ✗ ERS_Hector_EQ | 1212s | 1000s | +212s | 1.21× | 0/6 |
| ✗ ENVI_Baja_EQ_SLC | 1427s | 1210s | +217s | 1.18× | 0/6 |
| ✗ S1_Larsen_C | 4940s | 4289s | +651s | 1.15× | 0/10 |
| ✗ S1A_SLC_TOPS_COVE | 5494s | 5042s | +452s | 1.09× | 0/10 |
| ✗ ALOS2_SCAN_SSAF | 8864s | - | - | - | 0/14 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF, ALOS_haiti, NISAR_Ethiopia, S1A_SLC_TOPS_COVE, S1A_SLC_TOPS_Greece, S1A_SLC_TOPS_LA, S1_Larsen_C, S1_Ridgecrest_EQ_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| ENVI_Baja_EQ | **1288s** | 1000s | 51s | 20s | 0s | 28s | 7s |
| ENVI_Baja_EQ_SLC | **1208s** | 1120s | 26s | 22s | 0s | 15s | 22s |
| ALOS2_Japan_Fugi_left | **1115s** | 903s | 100s | 28s | 0s | 40s | 41s |
| ERS_Hector_EQ | **996s** | 797s | 31s | 20s | 0s | 17s | 3s |
| ALOS4_Pinon | **996s** | 873s | 37s | 17s | 0s | 20s | 25s |
| ALOS_Baja_EQ | **825s** | 402s | 48s | 21s | 0s | 53s | 38s |
| ALOS2_Brazil | **773s** | 691s | 33s | 17s | 0s | 19s | 11s |
| ALOS_ERSDAC_L1.0 | **649s** | 437s | 25s | 20s | 0s | 16s | 14s |
| CSK_SLC_Italy | **599s** | 439s | 74s | 28s | 0s | 38s | 18s |
| TSX_SLC_Hawaii | **531s** | 343s | 84s | 28s | 0s | 39s | 34s |
| CSK_RAW_Hawaii | **526s** | 79s | 80s | 50s | 0s | 37s | 12s |
| ALOS_SLC_L1.1 | **213s** | 119s | 28s | 17s | 0s | 15s | 19s |
| RS2_SLC_Hawaii | **72s** | 39s | 4s | 23s | 0s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 13 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 7241s | 82.7% | gmt-wrapper |
| resamp_py | 622s | 7.1% | Numba py |
| intf | 340s | 3.9% | C bin |
| xcorr_py | 311s | 3.6% | scipy.fft py |
| pre_proc | 245s | 2.8% | C bin |
| geocode | 0s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### ALOS2_Brazil — score 0/6, py=775s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS2_Japan_Fugi_left — score 0/6, py=1115s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS2_SCAN_SSAF — score 0/14, py=-

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS4_Pinon — score 0/6, py=997s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS_Baja_EQ — score 0/6, py=826s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS_ERSDAC_L1.0 — score 0/6, py=650s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS_SLC_L1.1 — score 0/6, py=213s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ALOS_haiti — score 0/6, py=1313s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### CSK_RAW_Hawaii — score 0/6, py=526s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### CSK_SLC_Italy — score 0/6, py=600s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ENVI_Baja_EQ — score 0/6, py=1288s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ENVI_Baja_EQ_SLC — score 0/6, py=1210s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### ERS_Hector_EQ — score 0/6, py=1000s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### NISAR_Ethiopia — score 0/6, py=176s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### RS2_SLC_Hawaii — score 0/6, py=72s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### S1A_SLC_TOPS_COVE — score 0/10, py=5042s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### S1A_SLC_TOPS_Greece — score 0/10, py=2432s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### S1A_SLC_TOPS_LA — score 0/10, py=5334s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### S1_Larsen_C — score 0/10, py=4289s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### S1_Ridgecrest_EQ — score 0/16, py=3013s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

### TSX_SLC_Hawaii — score 0/6, py=531s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | corr_ll.png missing on py |
| display_amp_ll.png | ✗ FAIL | display_amp_ll.png missing on py |
| phasefilt_mask_ll.png | ✗ FAIL | phasefilt_mask_ll.png missing on py |
| corr_ll.grd | ✗ FAIL | corr_ll.grd missing on py |
| phasefilt.grd | ✗ FAIL | phasefilt.grd missing on py |
| filtcorr.grd | ✗ FAIL | filtcorr.grd missing on py |

---

_Snapshot generated: 2026-06-18T05-21-13Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
