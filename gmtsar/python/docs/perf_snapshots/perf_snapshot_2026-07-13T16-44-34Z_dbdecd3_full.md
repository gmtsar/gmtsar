# Perf snapshot — full, 2026-07-13T16-44-34Z

**Commit:** `dbdecd3` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=(not constrained)`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, 1007.6G RAM, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 1m (109s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ NISAR_Ethiopia | 543s | 178s | +365s | 3.05× | 6/0 |
| ✓ RS2_SLC_Hawaii | 195s | 96s | +99s | 2.03× | 6/0 |
| ✓ CSK_RAW_Hawaii | 822s | 601s | +221s | 1.37× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 448s | 337s | +111s | 1.33× | 6/0 |
| ✓ TSX_SLC_Hawaii | 852s | 647s | +205s | 1.32× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9385s | 8139s | +1246s | 1.15× | 11/5 |
| ✓ ALOS2_SCAN_SSAF | 9016s | 7828s | +1188s | 1.15× | 14/0 |
| ✓ ALOS2_Brazil | 999s | 873s | +126s | 1.14× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 965s | 862s | +103s | 1.12× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1427s | 1288s | +139s | 1.11× | 6/0 |
| ✓ ALOS4_Pinon | 1267s | 1152s | +115s | 1.10× | 6/0 |
| ✓ ALOS_Baja_EQ | 1117s | 1024s | +93s | 1.09× | 6/0 |
| ✓ CSK_SLC_Italy | 843s | 773s | +70s | 1.09× | 6/0 |
| ✓ ENVI_Baja_EQ | 1767s | 1631s | +136s | 1.08× | 6/0 |
| ✓ ERS_Hector_EQ | 1276s | 1199s | +77s | 1.06× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6722s | 6408s | +314s | 1.05× | 10/0 |
| ✓ ENVI_Baja_EQ_SLC | 1461s | 1409s | +52s | 1.04× | 6/0 |
| ✓ ALOS_haiti | 1669s | 1647s | +22s | 1.01× | 7/0 |
| ✓ S1_Larsen_C | 5013s | 5078s | -65s | 0.99× | 10/0 |
| ✓ S1A_SLC_TOPS_Greece | 3028s | 3069s | -41s | 0.99× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5507s | 6035s | -528s | 0.91× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8845s** | 4775s | - | - | - | 77s | 538s |
| S1A_SLC_TOPS_COVE | **8486s** | 4473s | - | - | - | 68s | 507s |
| S1_Larsen_C | **7140s** | 3623s | - | - | - | 68s | 603s |
| S1A_SLC_TOPS_Greece | **5747s** | 5971s | - | - | - | 68s | 585s |
| S1_Ridgecrest_EQ | **3915s** | 3681s | - | - | - | 70s | 553s |
| ALOS_haiti | **1647s** | 898s | 50s | 24s | 81s | 53s | 12s |
| ENVI_Baja_EQ | **1631s** | 1009s | 48s | 38s | 181s | 32s | 6s |
| ENVI_Baja_EQ_SLC | **1409s** | 1127s | 30s | 20s | 112s | 17s | 27s |
| ALOS2_Japan_Fugi_left | **1288s** | 895s | 101s | 30s | 75s | 38s | 44s |
| ERS_Hector_EQ | **1197s** | 803s | 28s | 19s | 121s | 17s | 3s |
| ALOS4_Pinon | **1152s** | 879s | 38s | 17s | 77s | 25s | 13s |
| ALOS_Baja_EQ | **1024s** | 414s | 50s | 22s | 83s | 55s | 40s |
| ALOS2_Brazil | **873s** | 693s | 35s | 16s | 47s | 19s | 10s |
| ALOS_ERSDAC_L1.0 | **862s** | 446s | 26s | 47s | 95s | 17s | 8s |
| CSK_SLC_Italy | **773s** | 436s | 78s | 42s | 41s | 39s | 82s |
| TSX_SLC_Hawaii | **647s** | 341s | 83s | 27s | 58s | 39s | 19s |
| CSK_RAW_Hawaii | **601s** | 77s | 81s | 42s | 24s | 39s | 14s |
| ALOS_SLC_L1.1 | **337s** | 119s | 29s | 19s | 56s | 25s | 20s |
| NISAR_Ethiopia | **173s** | 30s | 6s | 37s | 51s | 4s | - |
| RS2_SLC_Hawaii | **96s** | 40s | 4s | 23s | 13s | 5s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 30730s | 78.5% | gmt-wrapper |
| pre_proc | 3085s | 7.9% | C bin |
| merge_unwrap_geocode_tops | 2194s | 5.6% | ? |
| geocode | 1115s | 2.8% | gmt-subprocess |
| intf | 776s | 2.0% | C bin |
| resamp_py | 687s | 1.8% | Numba py |
| xcorr_py | 423s | 1.1% | scipy.fft py |
| snaphu | 131s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### S1_Ridgecrest_EQ — score 11/5, py=8139s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | — |
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| corr_ll.grd | ✗ FAIL | — |
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

_Snapshot generated: 2026-07-13T16-44-34Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
