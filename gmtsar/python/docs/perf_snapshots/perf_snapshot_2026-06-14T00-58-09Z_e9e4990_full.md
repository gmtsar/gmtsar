# Perf snapshot — full, 2026-06-14T00-58-09Z

**Commit:** `e9e4990` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 3h 0m (10837s)  

**Coverage:** 21 cases with scorecards. **20 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 182s | 86s | +96s | 2.12× | 6/0 |
| ✓ NISAR_Ethiopia | 454s | 286s | +168s | 1.59× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 293s | +138s | 1.47× | 6/0 |
| ✓ TSX_SLC_Hawaii | 782s | 622s | +160s | 1.26× | 6/0 |
| ✗ CSK_SLC_Italy | 791s | 634s | +157s | 1.25× | 5/1 |
| ✓ ALOS2_SCAN_SSAF | 8961s | 7350s | +1611s | 1.22× | 14/0 |
| ✓ CSK_RAW_Hawaii | 726s | 607s | +119s | 1.20× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 760s | +144s | 1.19× | 6/0 |
| ✓ S1_Ridgecrest_EQ | 9244s | 7789s | +1455s | 1.19× | 16/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1200s | +183s | 1.15× | 6/0 |
| ✓ ALOS_Baja_EQ | 1046s | 912s | +134s | 1.15× | 6/0 |
| ✓ ALOS2_Brazil | 944s | 833s | +111s | 1.13× | 6/0 |
| ✓ ALOS4_Pinon | 1209s | 1072s | +137s | 1.13× | 6/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1541s | +194s | 1.13× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1276s | +151s | 1.12× | 6/0 |
| ✓ ERS_Hector_EQ | 1212s | 1096s | +116s | 1.11× | 6/0 |
| ✓ ALOS_haiti | 1713s | 1563s | +150s | 1.10× | 7/0 |
| ✓ S1A_SLC_TOPS_COVE | 5497s | 5096s | +401s | 1.08× | 10/0 |
| ✓ S1A_SLC_TOPS_LA | 6677s | 6200s | +477s | 1.08× | 10/0 |
| ✓ S1A_SLC_TOPS_Greece | 2998s | 2850s | +148s | 1.05× | 10/0 |
| ✓ S1_Larsen_C | 4965s | 4888s | +77s | 1.02× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8447s** | 4637s | - | - | - | 72s | 521s |
| S1A_SLC_TOPS_COVE | **7218s** | 3588s | - | - | - | 67s | 501s |
| S1_Larsen_C | **6860s** | 3486s | - | - | - | 67s | 600s |
| S1A_SLC_TOPS_Greece | **5320s** | 5497s | - | - | - | 70s | 586s |
| S1_Ridgecrest_EQ | **4270s** | 3951s | - | - | - | 71s | 605s |
| ALOS_haiti | **1562s** | 846s | 49s | 18s | 74s | 56s | 14s |
| ENVI_Baja_EQ | **1539s** | 960s | 50s | 21s | 169s | 29s | 6s |
| ENVI_Baja_EQ_SLC | **1276s** | 1016s | 26s | 21s | 105s | 17s | 22s |
| ALOS2_Japan_Fugi_left | **1199s** | 840s | 102s | 30s | 47s | 39s | 38s |
| ERS_Hector_EQ | **1094s** | 714s | 28s | 19s | 115s | 17s | 3s |
| ALOS4_Pinon | **1072s** | 819s | 37s | 19s | 68s | 25s | 17s |
| ALOS_Baja_EQ | **910s** | 313s | 49s | 18s | 79s | 57s | 50s |
| ALOS2_Brazil | **832s** | 639s | 33s | 16s | 57s | 18s | 13s |
| ALOS_ERSDAC_L1.0 | **759s** | 396s | 25s | 21s | 85s | 17s | 9s |
| CSK_SLC_Italy | **633s** | 394s | 74s | 29s | 34s | 37s | 16s |
| TSX_SLC_Hawaii | **622s** | 311s | 84s | 27s | 54s | 38s | 34s |
| CSK_RAW_Hawaii | **607s** | 73s | 79s | 49s | 23s | 42s | 17s |
| ALOS_SLC_L1.1 | **293s** | 104s | 28s | 17s | 50s | 15s | 20s |
| NISAR_Ethiopia | **283s** | 24s | 5s | 35s | 46s | 5s | - |
| RS2_SLC_Hawaii | **86s** | 32s | 4s | 24s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 28640s | 77.8% | gmt-wrapper |
| pre_proc | 3072s | 8.3% | C bin |
| merge_unwrap_geocode_tops | 2167s | 5.9% | ? |
| geocode | 1018s | 2.8% | gmt-subprocess |
| intf | 761s | 2.1% | C bin |
| resamp_py | 671s | 1.8% | Numba py |
| xcorr_py | 364s | 1.0% | scipy.fft py |
| snaphu | 119s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### CSK_SLC_Italy — score 5/1, py=634s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✗ FAIL | — |
| filtcorr.grd | ✓ SUCCESS | — |

---

_Snapshot generated: 2026-06-14T00-58-09Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
