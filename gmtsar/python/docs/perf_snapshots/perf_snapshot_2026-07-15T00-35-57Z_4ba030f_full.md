# Perf snapshot — full, 2026-07-15T00-35-57Z

**Commit:** `4ba030f` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=12 SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, 1007.6G RAM, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 37m (2269s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ NISAR_Ethiopia | 543s | 183s | +360s | 2.97× | 6/0 |
| ✓ RS2_SLC_Hawaii | 195s | 100s | +95s | 1.95× | 6/0 |
| ✓ CSK_RAW_Hawaii | 822s | 594s | +228s | 1.38× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 448s | 349s | +99s | 1.28× | 6/0 |
| ✓ TSX_SLC_Hawaii | 852s | 665s | +187s | 1.28× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9385s | 8134s | +1251s | 1.15× | 14/2 |
| ✓ ALOS_ERSDAC_L1.0 | 965s | 837s | +128s | 1.15× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 9016s | 7833s | +1183s | 1.15× | 14/0 |
| ✓ ALOS2_Brazil | 999s | 869s | +130s | 1.15× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1427s | 1288s | +139s | 1.11× | 6/0 |
| ✓ ALOS4_Pinon | 1267s | 1151s | +116s | 1.10× | 6/0 |
| ✓ CSK_SLC_Italy | 843s | 768s | +75s | 1.10× | 6/0 |
| ✓ ALOS_Baja_EQ | 1117s | 1036s | +81s | 1.08× | 6/0 |
| ✓ ENVI_Baja_EQ | 1767s | 1643s | +124s | 1.08× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6722s | 6382s | +340s | 1.05× | 10/0 |
| ✓ ERS_Hector_EQ | 1276s | 1222s | +54s | 1.04× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1461s | 1432s | +29s | 1.02× | 6/0 |
| ✓ ALOS_haiti | 1669s | 1656s | +13s | 1.01× | 7/0 |
| ✓ S1A_SLC_TOPS_Greece | 3028s | 3025s | +3s | 1.00× | 10/0 |
| ✓ S1_Larsen_C | 5013s | 5069s | -56s | 0.99× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5507s | 6022s | -515s | 0.91× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8807s** | 4772s | - | - | - | 71s | 526s |
| S1A_SLC_TOPS_COVE | **8458s** | 4479s | - | - | - | 67s | 492s |
| S1_Larsen_C | **7138s** | 3633s | - | - | - | 68s | 596s |
| S1A_SLC_TOPS_Greece | **5654s** | 5930s | - | - | - | 71s | 579s |
| S1_Ridgecrest_EQ | **3890s** | 3685s | - | - | - | 70s | 554s |
| ALOS_haiti | **1655s** | 877s | 49s | 36s | 86s | 55s | 11s |
| ENVI_Baja_EQ | **1642s** | 1011s | 69s | 38s | 171s | 29s | 6s |
| ENVI_Baja_EQ_SLC | **1432s** | 1136s | 26s | 28s | 124s | 18s | 23s |
| ALOS2_Japan_Fugi_left | **1288s** | 898s | 100s | 28s | 74s | 37s | 45s |
| ERS_Hector_EQ | **1219s** | 807s | 29s | 33s | 120s | 17s | 3s |
| ALOS4_Pinon | **1151s** | 879s | 37s | 19s | 73s | 22s | 18s |
| ALOS_Baja_EQ | **1036s** | 413s | 53s | 35s | 78s | 56s | 39s |
| ALOS2_Brazil | **869s** | 696s | 34s | 17s | 40s | 19s | 10s |
| ALOS_ERSDAC_L1.0 | **837s** | 445s | 26s | 31s | 97s | 16s | 7s |
| CSK_SLC_Italy | **768s** | 441s | 75s | 37s | 41s | 38s | 84s |
| TSX_SLC_Hawaii | **664s** | 348s | 82s | 30s | 59s | 43s | 18s |
| CSK_RAW_Hawaii | **594s** | 77s | 79s | 35s | 24s | 36s | 17s |
| ALOS_SLC_L1.1 | **349s** | 119s | 29s | 22s | 59s | 18s | 20s |
| NISAR_Ethiopia | **179s** | 29s | 7s | 41s | 48s | 7s | - |
| RS2_SLC_Hawaii | **100s** | 40s | 4s | 24s | 15s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 30714s | 78.6% | gmt-wrapper |
| pre_proc | 3050s | 7.8% | C bin |
| merge_unwrap_geocode_tops | 2181s | 5.6% | ? |
| geocode | 1108s | 2.8% | gmt-subprocess |
| intf | 764s | 2.0% | C bin |
| resamp_py | 700s | 1.8% | Numba py |
| xcorr_py | 457s | 1.2% | scipy.fft py |
| snaphu | 123s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### S1_Ridgecrest_EQ — score 14/2, py=8134s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
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

_Snapshot generated: 2026-07-15T00-35-57Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
