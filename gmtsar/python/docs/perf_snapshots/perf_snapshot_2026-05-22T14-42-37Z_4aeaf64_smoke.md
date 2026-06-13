# Perf snapshot — smoke, 2026-05-22T14-42-37Z

**Commit:** `4aeaf64` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=1`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** Python 3.11.0  
**Sweep wall:** 0h 19m (1162s)  

**Coverage:** 11 cases with scorecards. **11 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 183s | 94s | +89s | 1.95× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 306s | +117s | 1.38× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 344s | +103s | 1.30× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 601s | +138s | 1.23× | 6/0 |
| ✓ CSK_RAW_Hawaii | 703s | 602s | +101s | 1.17× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 806s | +129s | 1.16× | 6/0 |
| ✓ ALOS_Baja_EQ | 1076s | 931s | +145s | 1.16× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1068s | +162s | 1.15× | 6/0 |
| ✓ ERS_Hector_EQ | 1244s | 1121s | +123s | 1.11× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1273s | +134s | 1.11× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1646s | +103s | 1.06× | 7/0 |

## Table 2 — Per-binary timing (single-pair cases only)

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| ALOS_haiti | **1646s** | 876s | 66s | 35s | 71s | 54s | 13s |
| ENVI_Baja_EQ_SLC | **1273s** | 1021s | 28s | 21s | 102s | 16s | 22s |
| ERS_Hector_EQ | **1120s** | 719s | 28s | 28s | 111s | 18s | 7s |
| ALOS4_Pinon | **1067s** | 818s | 38s | 18s | 67s | 21s | 24s |
| ALOS_Baja_EQ | **931s** | 314s | 50s | 27s | 74s | 53s | 67s |
| ALOS2_Brazil | **806s** | 638s | 33s | 18s | 31s | 18s | 19s |
| CSK_RAW_Hawaii | **601s** | 73s | 80s | 47s | 23s | 35s | 20s |
| TSX_SLC_Hawaii | **601s** | 311s | 81s | 29s | 54s | 42s | 13s |
| NISAR_Ethiopia | **340s** | 25s | 6s | 42s | 52s | 6s | - |
| ALOS_SLC_L1.1 | **306s** | 106s | 31s | 20s | 50s | 16s | 20s |
| RS2_SLC_Hawaii | **93s** | 34s | 4s | 23s | 15s | 5s | 1s |

## Table 3 — Aggregate cost by stage (across 11 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 4935s | 71.0% | gmt-wrapper |
| geocode | 649s | 9.3% | gmt-subprocess |
| resamp_py | 445s | 6.4% | Numba py |
| xcorr_py | 310s | 4.5% | scipy.fft py |
| intf | 284s | 4.1% | C bin |
| pre_proc | 206s | 3.0% | C bin |
| snaphu | 118s | 1.7% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-05-22T14-42-37Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
