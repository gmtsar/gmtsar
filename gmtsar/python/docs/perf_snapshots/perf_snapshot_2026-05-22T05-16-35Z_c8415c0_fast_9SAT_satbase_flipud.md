# Perf snapshot — fast_9SAT_satbase_flipud, 2026-05-22T05-16-35Z

**Commit:** `c8415c0`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=(not constrained)`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 1 cores, nfs workdir (theo2)  
**Software:** Python 3.11.0  
**Sweep wall:** 0h 2m (127s)  

**Coverage:** 21 cases with scorecards. **21 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 175s | 111s | +64s | 1.58× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 299s | +148s | 1.49× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 8922s | 7858s | +1064s | 1.14× | 14/0 |
| ✓ S1_Ridgecrest_EQ | 9148s | 8248s | +900s | 1.11× | 16/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 397s | +26s | 1.07× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1207s | +23s | 1.02× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1720s | +29s | 1.02× | 7/0 |
| ✓ ALOS2_Brazil | 935s | 920s | +15s | 1.02× | 6/0 |
| ✓ ENVI_Baja_EQ | 1740s | 1717s | +23s | 1.01× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 911s | 899s | +12s | 1.01× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6687s | 6657s | +30s | 1.00× | 10/0 |
| ✓ S1_Larsen_C | 4948s | 4934s | +14s | 1.00× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5507s | 5492s | +15s | 1.00× | 10/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1404s | +3s | 1.00× | 6/0 |
| ✓ S1A_SLC_TOPS_Greece | 3003s | 3015s | -12s | 1.00× | 10/0 |
| ✓ ERS_Hector_EQ | 1244s | 1265s | -21s | 0.98× | 6/0 |
| ✓ ALOS_Baja_EQ | 1076s | 1098s | -22s | 0.98× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1346s | 1574s | -228s | 0.86× | 6/0 |
| ✓ CSK_SLC_Italy | 803s | 978s | -175s | 0.82× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 970s | -231s | 0.76× | 6/0 |
| ✓ CSK_RAW_Hawaii | 703s | 932s | -229s | 0.75× | 6/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF, S1A_SLC_TOPS_COVE, S1A_SLC_TOPS_Greece, S1A_SLC_TOPS_LA, S1_Larsen_C, S1_Ridgecrest_EQ_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| ALOS_haiti | **1720s** | 849s | 201s | 28s | 70s | 52s | 12s |
| ENVI_Baja_EQ | **1717s** | 982s | 201s | 28s | 172s | 27s | 7s |
| ALOS2_Japan_Fugi_left | **1574s** | 856s | 443s | 28s | 51s | 46s | 44s |
| ENVI_Baja_EQ_SLC | **1404s** | 1083s | 102s | 21s | 99s | 14s | 22s |
| ERS_Hector_EQ | **1265s** | 812s | 111s | 23s | 109s | 16s | 3s |
| ALOS4_Pinon | **1208s** | 845s | 155s | 18s | 66s | 19s | 23s |
| ALOS_Baja_EQ | **1098s** | 352s | 201s | 29s | 75s | 52s | 41s |
| CSK_SLC_Italy | **978s** | 403s | 398s | 28s | 37s | 41s | 20s |
| TSX_SLC_Hawaii | **970s** | 330s | 433s | 29s | 53s | 41s | 14s |
| CSK_RAW_Hawaii | **932s** | 92s | 412s | 36s | 24s | 40s | 14s |
| ALOS2_Brazil | **920s** | 649s | 135s | 19s | 33s | 17s | 20s |
| ALOS_ERSDAC_L1.0 | **898s** | 435s | 103s | 28s | 93s | 13s | 12s |
| ALOS_SLC_L1.1 | **397s** | 120s | 114s | 20s | 49s | 14s | 20s |
| NISAR_Ethiopia | **297s** | 31s | 22s | 43s | 38s | 3s | - |
| RS2_SLC_Hawaii | **111s** | 49s | 11s | 26s | 14s | 2s | 1s |

## Table 3 — Aggregate cost by stage (across 15 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 7888s | 60.3% | gmt-wrapper |
| resamp_py | 3043s | 23.3% | Numba py |
| geocode | 982s | 7.5% | gmt-subprocess |
| xcorr_py | 404s | 3.1% | scipy.fft py |
| intf | 396s | 3.0% | C bin |
| pre_proc | 251s | 1.9% | C bin |
| snaphu | 122s | 0.9% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-05-22T05-16-35Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
