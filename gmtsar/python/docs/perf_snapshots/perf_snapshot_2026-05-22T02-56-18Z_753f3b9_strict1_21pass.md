# Perf snapshot — strict1_21pass, 2026-05-22T02-56-18Z

**Commit:** `753f3b9` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=(not constrained)`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 1 cores, nfs workdir (theo2)  
**Software:** Python 3.11.0  
**Sweep wall:** 0h 16m (966s)  

**Coverage:** 21 cases with scorecards. **21 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 175s | 109s | +66s | 1.61× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 334s | +113s | 1.34× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 8922s | 7858s | +1064s | 1.14× | 14/0 |
| ✓ S1_Ridgecrest_EQ | 9148s | 8248s | +900s | 1.11× | 16/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 411s | +12s | 1.03× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1720s | +29s | 1.02× | 7/0 |
| ✓ ENVI_Baja_EQ | 1740s | 1717s | +23s | 1.01× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 911s | 899s | +12s | 1.01× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 927s | +8s | 1.01× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1221s | +9s | 1.01× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6687s | 6657s | +30s | 1.00× | 10/0 |
| ✓ S1_Larsen_C | 4948s | 4934s | +14s | 1.00× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5507s | 5492s | +15s | 1.00× | 10/0 |
| ✓ S1A_SLC_TOPS_Greece | 3003s | 3015s | -12s | 1.00× | 10/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1426s | -19s | 0.99× | 6/0 |
| ✓ ALOS_Baja_EQ | 1076s | 1098s | -22s | 0.98× | 6/0 |
| ✓ ERS_Hector_EQ | 1244s | 1295s | -51s | 0.96× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1346s | 1574s | -228s | 0.86× | 6/0 |
| ✓ CSK_SLC_Italy | 803s | 978s | -175s | 0.82× | 6/0 |
| ✓ CSK_RAW_Hawaii | 703s | 934s | -231s | 0.75× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 982s | -243s | 0.75× | 6/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF, S1A_SLC_TOPS_COVE, S1A_SLC_TOPS_Greece, S1A_SLC_TOPS_LA, S1_Larsen_C, S1_Ridgecrest_EQ_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| ALOS_haiti | **1720s** | 849s | 201s | 28s | 70s | 52s | 12s |
| ENVI_Baja_EQ | **1717s** | 982s | 201s | 28s | 172s | 27s | 7s |
| ALOS2_Japan_Fugi_left | **1574s** | 856s | 443s | 28s | 51s | 46s | 44s |
| ENVI_Baja_EQ_SLC | **1424s** | 1088s | 105s | 28s | 104s | 15s | 21s |
| ERS_Hector_EQ | **1294s** | 816s | 113s | 28s | 118s | 18s | 3s |
| ALOS4_Pinon | **1221s** | 848s | 155s | 28s | 74s | 20s | 12s |
| ALOS_Baja_EQ | **1098s** | 352s | 201s | 29s | 75s | 52s | 41s |
| TSX_SLC_Hawaii | **982s** | 334s | 434s | 27s | 54s | 45s | 16s |
| CSK_SLC_Italy | **978s** | 403s | 398s | 28s | 37s | 41s | 20s |
| CSK_RAW_Hawaii | **934s** | 95s | 406s | 34s | 26s | 44s | 14s |
| ALOS2_Brazil | **927s** | 651s | 141s | 27s | 31s | 17s | 12s |
| ALOS_ERSDAC_L1.0 | **898s** | 435s | 103s | 28s | 93s | 13s | 12s |
| ALOS_SLC_L1.1 | **411s** | 122s | 112s | 36s | 48s | 14s | 20s |
| NISAR_Ethiopia | **328s** | 32s | 24s | 43s | 54s | 3s | - |
| RS2_SLC_Hawaii | **109s** | 49s | 11s | 27s | 12s | 2s | 1s |

## Table 3 — Aggregate cost by stage (across 15 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 7913s | 60.0% | gmt-wrapper |
| resamp_py | 3048s | 23.1% | Numba py |
| geocode | 1020s | 7.7% | gmt-subprocess |
| xcorr_py | 448s | 3.4% | scipy.fft py |
| intf | 407s | 3.1% | C bin |
| pre_proc | 233s | 1.8% | C bin |
| snaphu | 122s | 0.9% | C bin |
| fitoffset_ra | 2s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-05-22T02-56-18Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
