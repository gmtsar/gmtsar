# Perf snapshot — full, 2026-06-16T03-52-18Z

**Commit:** `b35d384` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 3h 0m (10820s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 182s | 96s | +86s | 1.90× | 6/0 |
| ✓ NISAR_Ethiopia | 454s | 297s | +157s | 1.53× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 327s | +104s | 1.32× | 6/0 |
| ✓ CSK_RAW_Hawaii | 726s | 625s | +101s | 1.16× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9183s | 8101s | +1082s | 1.13× | 15/1 |
| ✓ TSX_SLC_Hawaii | 782s | 691s | +91s | 1.13× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 8924s | 7972s | +952s | 1.12× | 14/0 |
| ✓ CSK_SLC_Italy | 791s | 723s | +68s | 1.09× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1289s | +94s | 1.07× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 865s | +39s | 1.05× | 6/0 |
| ✓ ALOS2_Brazil | 944s | 906s | +38s | 1.04× | 6/0 |
| ✓ ALOS_haiti | 1713s | 1645s | +68s | 1.04× | 7/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1670s | +65s | 1.04× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6679s | 6531s | +148s | 1.02× | 10/0 |
| ✓ S1_Larsen_C | 4955s | 5077s | -122s | 0.98× | 10/0 |
| ✓ ALOS4_Pinon | 1209s | 1254s | -45s | 0.96× | 6/0 |
| ✓ ALOS_Baja_EQ | 1046s | 1089s | -43s | 0.96× | 6/0 |
| ✓ S1A_SLC_TOPS_Greece | 3010s | 3136s | -126s | 0.96× | 10/0 |
| ✓ ERS_Hector_EQ | 1212s | 1284s | -72s | 0.94× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1531s | -104s | 0.93× | 6/0 |
| ✓ S1A_SLC_TOPS_COVE | 5501s | 6102s | -601s | 0.90× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **9030s** | 4927s | - | - | - | 73s | 522s |
| S1A_SLC_TOPS_COVE | **8585s** | 4568s | - | - | - | 70s | 497s |
| S1_Larsen_C | **7143s** | 3642s | - | - | - | 68s | 596s |
| S1A_SLC_TOPS_Greece | **5865s** | 6148s | - | - | - | 74s | 575s |
| S1_Ridgecrest_EQ | **3924s** | 3771s | - | - | - | 65s | 526s |
| ENVI_Baja_EQ | **1667s** | 1052s | 48s | 20s | 181s | 30s | 6s |
| ALOS_haiti | **1644s** | 898s | 48s | 18s | 75s | 55s | 12s |
| ENVI_Baja_EQ_SLC | **1531s** | 1265s | 25s | 22s | 107s | 18s | 21s |
| ALOS2_Japan_Fugi_left | **1289s** | 916s | 101s | 31s | 50s | 38s | 46s |
| ERS_Hector_EQ | **1283s** | 891s | 30s | 20s | 115s | 18s | 4s |
| ALOS4_Pinon | **1252s** | 977s | 38s | 17s | 70s | 21s | 32s |
| ALOS_Baja_EQ | **1086s** | 461s | 51s | 25s | 83s | 54s | 52s |
| ALOS2_Brazil | **905s** | 702s | 33s | 16s | 39s | 23s | 10s |
| ALOS_ERSDAC_L1.0 | **865s** | 491s | 25s | 21s | 89s | 17s | 7s |
| CSK_SLC_Italy | **723s** | 457s | 77s | 32s | 35s | 40s | 28s |
| TSX_SLC_Hawaii | **690s** | 355s | 83s | 28s | 72s | 42s | 31s |
| CSK_RAW_Hawaii | **623s** | 79s | 85s | 52s | 25s | 39s | 17s |
| ALOS_SLC_L1.1 | **326s** | 131s | 28s | 17s | 50s | 15s | 19s |
| NISAR_Ethiopia | **293s** | 29s | 6s | 36s | 45s | 5s | - |
| RS2_SLC_Hawaii | **96s** | 42s | 4s | 23s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 31803s | 79.5% | gmt-wrapper |
| pre_proc | 3003s | 7.5% | C bin |
| merge_unwrap_geocode_tops | 2172s | 5.4% | ? |
| geocode | 1049s | 2.6% | gmt-subprocess |
| intf | 770s | 1.9% | C bin |
| resamp_py | 682s | 1.7% | Numba py |
| xcorr_py | 379s | 0.9% | scipy.fft py |
| snaphu | 136s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### S1_Ridgecrest_EQ — score 15/1, py=8101s

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

_Snapshot generated: 2026-06-16T03-52-18Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
