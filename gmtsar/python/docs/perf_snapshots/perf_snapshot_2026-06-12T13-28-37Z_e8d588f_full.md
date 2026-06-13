# Perf snapshot — full, 2026-06-12T13-28-37Z

**Commit:** `e8d588f`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=1 SWEEP_FORCE=1`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 3h 2m (10952s)  

**Coverage:** 21 cases with scorecards. **21 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 176s | 85s | +91s | 2.07× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 275s | +172s | 1.63× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 303s | +120s | 1.40× | 6/0 |
| ✓ CSK_RAW_Hawaii | 841s | 617s | +224s | 1.36× | 6/0 |
| ✓ CSK_SLC_Italy | 803s | 643s | +160s | 1.25× | 6/0 |
| ✓ ALOS_Baja_EQ | 1101s | 893s | +208s | 1.23× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 8918s | 7344s | +1574s | 1.21× | 14/0 |
| ✓ TSX_SLC_Hawaii | 739s | 610s | +129s | 1.21× | 6/0 |
| ✓ S1_Ridgecrest_EQ | 9147s | 7668s | +1479s | 1.19× | 16/0 |
| ✓ ALOS_ERSDAC_L1.0 | 911s | 774s | +137s | 1.18× | 6/0 |
| ✓ ERS_Hector_EQ | 1287s | 1102s | +185s | 1.17× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 806s | +129s | 1.16× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1074s | +156s | 1.15× | 6/0 |
| ✓ ENVI_Baja_EQ | 1740s | 1544s | +196s | 1.13× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1552s | +197s | 1.13× | 7/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1273s | +134s | 1.11× | 6/0 |
| ✓ S1A_SLC_TOPS_COVE | 5473s | 5073s | +400s | 1.08× | 10/0 |
| ✓ S1A_SLC_TOPS_LA | 6668s | 6195s | +473s | 1.08× | 10/0 |
| ✓ ALOS2_Japan_Fugi_left | 1346s | 1273s | +73s | 1.06× | 6/0 |
| ✓ S1A_SLC_TOPS_Greece | 3000s | 2866s | +134s | 1.05× | 10/0 |
| ✓ S1_Larsen_C | 4937s | 4857s | +80s | 1.02× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8436s** | 4637s | - | - | - | 67s | 521s |
| S1A_SLC_TOPS_COVE | **7187s** | 3587s | - | - | - | 67s | 484s |
| S1_Larsen_C | **6821s** | 3486s | - | - | - | 68s | 578s |
| S1A_SLC_TOPS_Greece | **5339s** | 5502s | - | - | - | 68s | 609s |
| S1_Ridgecrest_EQ | **4231s** | 3943s | - | - | - | 68s | 568s |
| ALOS_haiti | **1552s** | 844s | 51s | 38s | 66s | 52s | 13s |
| ENVI_Baja_EQ | **1544s** | 958s | 48s | 27s | 169s | 29s | 6s |
| ALOS2_Japan_Fugi_left | **1270s** | 839s | 101s | 29s | 48s | 37s | 110s |
| ENVI_Baja_EQ_SLC | **1269s** | 1021s | 25s | 20s | 101s | 18s | 21s |
| ERS_Hector_EQ | **1101s** | 718s | 27s | 27s | 116s | 17s | 4s |
| ALOS4_Pinon | **1073s** | 826s | 37s | 16s | 66s | 28s | 16s |
| ALOS_Baja_EQ | **893s** | 314s | 50s | 25s | 72s | 51s | 40s |
| ALOS2_Brazil | **802s** | 638s | 34s | 15s | 32s | 18s | 15s |
| ALOS_ERSDAC_L1.0 | **773s** | 398s | 25s | 20s | 97s | 18s | 11s |
| CSK_SLC_Italy | **643s** | 399s | 74s | 26s | 34s | 38s | 22s |
| CSK_RAW_Hawaii | **616s** | 75s | 80s | 63s | 21s | 37s | 15s |
| TSX_SLC_Hawaii | **610s** | 311s | 84s | 27s | 58s | 40s | 19s |
| ALOS_SLC_L1.1 | **300s** | 106s | 28s | 17s | 49s | 15s | 22s |
| NISAR_Ethiopia | **270s** | 25s | 7s | 36s | 39s | 5s | - |
| RS2_SLC_Hawaii | **85s** | 32s | 4s | 23s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 28658s | 77.9% | gmt-wrapper |
| pre_proc | 3074s | 8.4% | C bin |
| merge_unwrap_geocode_tops | 2156s | 5.9% | ? |
| geocode | 978s | 2.7% | gmt-subprocess |
| intf | 745s | 2.0% | C bin |
| resamp_py | 675s | 1.8% | Numba py |
| xcorr_py | 409s | 1.1% | scipy.fft py |
| snaphu | 108s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-06-12T13-28-37Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
