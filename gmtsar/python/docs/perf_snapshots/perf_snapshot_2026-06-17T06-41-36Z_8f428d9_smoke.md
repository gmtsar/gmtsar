# Perf snapshot — smoke, 2026-06-17T06-41-36Z

**Commit:** `8f428d9` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 2m (129s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 182s | 92s | +90s | 1.98× | 6/0 |
| ✓ NISAR_Ethiopia | 454s | 300s | +154s | 1.51× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 331s | +100s | 1.30× | 6/0 |
| ✓ CSK_RAW_Hawaii | 726s | 625s | +101s | 1.16× | 6/0 |
| ✓ TSX_SLC_Hawaii | 782s | 674s | +108s | 1.16× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9235s | 8150s | +1085s | 1.13× | 15/1 |
| ✓ ALOS2_SCAN_SSAF | 8947s | 7988s | +959s | 1.12× | 14/0 |
| ✓ CSK_SLC_Italy | 791s | 714s | +77s | 1.11× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1282s | +101s | 1.08× | 6/0 |
| ✓ ALOS_haiti | 1713s | 1625s | +88s | 1.05× | 7/0 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 861s | +43s | 1.05× | 6/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1654s | +81s | 1.05× | 6/0 |
| ✓ ALOS2_Brazil | 944s | 919s | +25s | 1.03× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6683s | 6525s | +158s | 1.02× | 10/0 |
| ✓ ALOS4_Pinon | 1209s | 1233s | -24s | 0.98× | 6/0 |
| ✓ S1_Larsen_C | 4968s | 5074s | -106s | 0.98× | 10/0 |
| ✓ S1A_SLC_TOPS_Greece | 3012s | 3117s | -105s | 0.97× | 10/0 |
| ✓ ALOS_Baja_EQ | 1046s | 1091s | -45s | 0.96× | 6/0 |
| ✓ ERS_Hector_EQ | 1212s | 1284s | -72s | 0.94× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1526s | -99s | 0.94× | 6/0 |
| ✓ S1A_SLC_TOPS_COVE | 5496s | 6098s | -602s | 0.90× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **9025s** | 4926s | - | - | - | 70s | 524s |
| S1A_SLC_TOPS_COVE | **8581s** | 4569s | - | - | - | 69s | 492s |
| S1_Larsen_C | **7130s** | 3637s | - | - | - | 68s | 594s |
| S1A_SLC_TOPS_Greece | **5827s** | 6100s | - | - | - | 75s | 587s |
| S1_Ridgecrest_EQ | **4047s** | 3799s | - | - | - | 75s | 601s |
| ENVI_Baja_EQ | **1652s** | 1055s | 48s | 20s | 174s | 30s | 6s |
| ALOS_haiti | **1624s** | 899s | 50s | 18s | 75s | 55s | 15s |
| ENVI_Baja_EQ_SLC | **1524s** | 1261s | 25s | 20s | 106s | 18s | 22s |
| ERS_Hector_EQ | **1281s** | 884s | 28s | 19s | 117s | 19s | 3s |
| ALOS2_Japan_Fugi_left | **1280s** | 912s | 102s | 29s | 47s | 39s | 43s |
| ALOS4_Pinon | **1232s** | 976s | 38s | 18s | 71s | 22s | 17s |
| ALOS_Baja_EQ | **1087s** | 462s | 49s | 23s | 77s | 57s | 57s |
| ALOS2_Brazil | **918s** | 706s | 33s | 16s | 49s | 24s | 13s |
| ALOS_ERSDAC_L1.0 | **861s** | 487s | 25s | 21s | 90s | 18s | 7s |
| CSK_SLC_Italy | **713s** | 451s | 76s | 30s | 34s | 41s | 27s |
| TSX_SLC_Hawaii | **673s** | 354s | 86s | 28s | 63s | 37s | 27s |
| CSK_RAW_Hawaii | **624s** | 77s | 80s | 58s | 25s | 39s | 24s |
| ALOS_SLC_L1.1 | **331s** | 130s | 28s | 17s | 57s | 15s | 20s |
| NISAR_Ethiopia | **295s** | 30s | 7s | 36s | 43s | 5s | - |
| RS2_SLC_Hawaii | **92s** | 38s | 4s | 24s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 31754s | 79.4% | gmt-wrapper |
| pre_proc | 3081s | 7.7% | C bin |
| merge_unwrap_geocode_tops | 2186s | 5.5% | ? |
| geocode | 1039s | 2.6% | gmt-subprocess |
| intf | 779s | 1.9% | C bin |
| resamp_py | 680s | 1.7% | Numba py |
| xcorr_py | 377s | 0.9% | scipy.fft py |
| snaphu | 116s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### S1_Ridgecrest_EQ — score 15/1, py=8150s

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

_Snapshot generated: 2026-06-17T06-41-36Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
