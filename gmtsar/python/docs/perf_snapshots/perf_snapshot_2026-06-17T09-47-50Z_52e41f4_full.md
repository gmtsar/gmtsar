# Perf snapshot — full, 2026-06-17T09-47-50Z

**Commit:** `52e41f4` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 2m (121s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 182s | 93s | +89s | 1.96× | 6/0 |
| ✓ NISAR_Ethiopia | 454s | 295s | +159s | 1.54× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 312s | +119s | 1.38× | 6/0 |
| ✓ TSX_SLC_Hawaii | 782s | 672s | +110s | 1.16× | 6/0 |
| ✓ CSK_RAW_Hawaii | 726s | 629s | +97s | 1.15× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9241s | 8057s | +1184s | 1.15× | 15/1 |
| ✓ ALOS2_SCAN_SSAF | 8919s | 7853s | +1066s | 1.14× | 14/0 |
| ✓ CSK_SLC_Italy | 791s | 697s | +94s | 1.13× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 811s | +93s | 1.11× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1266s | +117s | 1.09× | 6/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1616s | +119s | 1.07× | 6/0 |
| ✓ ALOS_haiti | 1713s | 1621s | +92s | 1.06× | 7/0 |
| ✓ ALOS2_Brazil | 944s | 897s | +47s | 1.05× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6687s | 6358s | +329s | 1.05× | 10/0 |
| ✓ ALOS4_Pinon | 1209s | 1156s | +53s | 1.05× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1390s | +37s | 1.03× | 6/0 |
| ✓ ALOS_Baja_EQ | 1046s | 1028s | +18s | 1.02× | 6/0 |
| ✓ ERS_Hector_EQ | 1212s | 1200s | +12s | 1.01× | 6/0 |
| ✓ S1A_SLC_TOPS_Greece | 3005s | 3021s | -16s | 0.99× | 10/0 |
| ✓ S1_Larsen_C | 4948s | 5067s | -119s | 0.98× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5497s | 6024s | -527s | 0.91× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8780s** | 4757s | - | - | - | 69s | 522s |
| S1A_SLC_TOPS_COVE | **8467s** | 4486s | - | - | - | 68s | 496s |
| S1_Larsen_C | **7124s** | 3617s | - | - | - | 67s | 597s |
| S1A_SLC_TOPS_Greece | **5641s** | 5897s | - | - | - | 70s | 575s |
| S1_Ridgecrest_EQ | **3943s** | 3669s | - | - | - | 74s | 596s |
| ALOS_haiti | **1619s** | 881s | 49s | 20s | 75s | 56s | 14s |
| ENVI_Baja_EQ | **1615s** | 1010s | 48s | 27s | 172s | 33s | 7s |
| ENVI_Baja_EQ_SLC | **1389s** | 1121s | 29s | 20s | 102s | 16s | 21s |
| ALOS2_Japan_Fugi_left | **1265s** | 896s | 102s | 30s | 47s | 37s | 47s |
| ERS_Hector_EQ | **1197s** | 802s | 28s | 21s | 119s | 20s | 3s |
| ALOS4_Pinon | **1154s** | 876s | 37s | 18s | 74s | 22s | 31s |
| ALOS_Baja_EQ | **1025s** | 405s | 52s | 25s | 75s | 61s | 50s |
| ALOS2_Brazil | **896s** | 693s | 34s | 16s | 49s | 24s | 12s |
| ALOS_ERSDAC_L1.0 | **811s** | 439s | 26s | 22s | 86s | 16s | 7s |
| CSK_SLC_Italy | **697s** | 436s | 74s | 32s | 34s | 39s | 29s |
| TSX_SLC_Hawaii | **670s** | 342s | 82s | 29s | 67s | 37s | 35s |
| CSK_RAW_Hawaii | **627s** | 78s | 82s | 62s | 24s | 35s | 19s |
| ALOS_SLC_L1.1 | **312s** | 118s | 27s | 16s | 51s | 15s | 20s |
| NISAR_Ethiopia | **291s** | 28s | 5s | 36s | 44s | 5s | - |
| RS2_SLC_Hawaii | **92s** | 38s | 4s | 23s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 30590s | 78.7% | gmt-wrapper |
| pre_proc | 3082s | 7.9% | C bin |
| merge_unwrap_geocode_tops | 2184s | 5.6% | ? |
| geocode | 1033s | 2.7% | gmt-subprocess |
| intf | 770s | 2.0% | C bin |
| resamp_py | 679s | 1.7% | Numba py |
| xcorr_py | 398s | 1.0% | scipy.fft py |
| snaphu | 112s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### S1_Ridgecrest_EQ — score 15/1, py=8057s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| corr_ll.grd | ✓ SUCCESS | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✗ FAIL | — |
| phasefilt.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |

---

_Snapshot generated: 2026-06-17T09-47-50Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
