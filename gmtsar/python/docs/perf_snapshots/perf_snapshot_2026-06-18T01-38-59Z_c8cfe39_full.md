# Perf snapshot — full, 2026-06-18T01-38-59Z

**Commit:** `c8cfe39`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 3h 0m (10848s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 182s | 93s | +89s | 1.96× | 6/0 |
| ✓ NISAR_Ethiopia | 454s | 294s | +160s | 1.54× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 311s | +120s | 1.39× | 6/0 |
| ✓ CSK_RAW_Hawaii | 726s | 617s | +109s | 1.18× | 6/0 |
| ✓ TSX_SLC_Hawaii | 782s | 679s | +103s | 1.15× | 6/0 |
| ✓ CSK_SLC_Italy | 791s | 691s | +100s | 1.14× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 8935s | 7846s | +1089s | 1.14× | 14/0 |
| ✗ S1_Ridgecrest_EQ | 9244s | 8124s | +1120s | 1.14× | 15/1 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 806s | +98s | 1.12× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1264s | +119s | 1.09× | 6/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1607s | +128s | 1.08× | 6/0 |
| ✓ ALOS_haiti | 1713s | 1619s | +94s | 1.06× | 7/0 |
| ✓ S1A_SLC_TOPS_LA | 6697s | 6383s | +314s | 1.05× | 10/0 |
| ✓ ALOS2_Brazil | 944s | 906s | +38s | 1.04× | 6/0 |
| ✓ ALOS4_Pinon | 1209s | 1162s | +47s | 1.04× | 6/0 |
| ✓ ALOS_Baja_EQ | 1046s | 1022s | +24s | 1.02× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1411s | +16s | 1.01× | 6/0 |
| ✓ ERS_Hector_EQ | 1212s | 1216s | -4s | 1.00× | 6/0 |
| ✓ S1A_SLC_TOPS_Greece | 3006s | 3017s | -11s | 1.00× | 10/0 |
| ✓ S1_Larsen_C | 4951s | 5068s | -117s | 0.98× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5506s | 6035s | -529s | 0.91× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8817s** | 4755s | - | - | - | 69s | 527s |
| S1A_SLC_TOPS_COVE | **8473s** | 4498s | - | - | - | 67s | 498s |
| S1_Larsen_C | **7137s** | 3626s | - | - | - | 67s | 600s |
| S1A_SLC_TOPS_Greece | **5635s** | 5893s | - | - | - | 72s | 593s |
| S1_Ridgecrest_EQ | **3946s** | 3667s | - | - | - | 72s | 648s |
| ALOS_haiti | **1617s** | 874s | 48s | 18s | 73s | 54s | 13s |
| ENVI_Baja_EQ | **1606s** | 1001s | 48s | 21s | 171s | 32s | 7s |
| ENVI_Baja_EQ_SLC | **1403s** | 1120s | 25s | 21s | 105s | 17s | 38s |
| ALOS2_Japan_Fugi_left | **1263s** | 893s | 100s | 31s | 47s | 37s | 50s |
| ERS_Hector_EQ | **1209s** | 801s | 27s | 20s | 121s | 18s | 19s |
| ALOS4_Pinon | **1154s** | 877s | 38s | 20s | 69s | 20s | 34s |
| ALOS_Baja_EQ | **1020s** | 403s | 52s | 23s | 77s | 54s | 51s |
| ALOS2_Brazil | **906s** | 700s | 34s | 16s | 54s | 18s | 12s |
| ALOS_ERSDAC_L1.0 | **806s** | 437s | 25s | 22s | 87s | 16s | 7s |
| CSK_SLC_Italy | **691s** | 435s | 76s | 31s | 33s | 38s | 25s |
| TSX_SLC_Hawaii | **674s** | 341s | 85s | 29s | 63s | 39s | 38s |
| CSK_RAW_Hawaii | **617s** | 79s | 80s | 58s | 23s | 36s | 16s |
| ALOS_SLC_L1.1 | **311s** | 118s | 27s | 17s | 49s | 15s | 19s |
| NISAR_Ethiopia | **291s** | 28s | 7s | 37s | 45s | 5s | - |
| RS2_SLC_Hawaii | **92s** | 38s | 4s | 23s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 30585s | 78.6% | gmt-wrapper |
| pre_proc | 3195s | 8.2% | C bin |
| merge_unwrap_geocode_tops | 2175s | 5.6% | ? |
| geocode | 1030s | 2.6% | gmt-subprocess |
| intf | 750s | 1.9% | C bin |
| resamp_py | 677s | 1.7% | Numba py |
| xcorr_py | 386s | 1.0% | scipy.fft py |
| snaphu | 128s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### S1_Ridgecrest_EQ — score 15/1, py=8124s

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

_Snapshot generated: 2026-06-18T01-38-59Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
